import json
import math
from pathlib import Path

import pytest
import shapefile

from pywr_editor.model import GisLayerConfig
from pywr_editor.schematic.map import GisLayerError, GisLayerLoader
from pywr_editor.schematic.map.gis_overlay import MAX_VERTICES

R = 6378137.0
""" The Web Mercator earth radius """


def lon_to_merc(lon: float) -> float:
    """
    Hand-computed Web Mercator x coordinate (the spherical Mercator formula).
    """
    return R * math.radians(lon)


def lat_to_merc(lat: float) -> float:
    """
    Hand-computed Web Mercator y coordinate (the spherical Mercator formula).
    """
    return R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def layer(path: Path, **kwargs) -> GisLayerConfig:
    return GisLayerConfig(layer_dict={"id": "aaa", "path": str(path), **kwargs})


def write_geojson(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data))
    return path


def feature(geometry: dict | None) -> dict:
    return {"type": "Feature", "properties": {}, "geometry": geometry}


class TestGeoJsonLoader:
    def test_reprojects_every_geometry_type(self, tmp_path):
        """
        The coordinates are compared against the spherical Mercator formulae.
        """
        data = {
            "type": "FeatureCollection",
            "features": [
                feature({"type": "Point", "coordinates": [-1.5, 52.1]}),
                feature({"type": "MultiPoint", "coordinates": [[0, 0], [10, 20]]}),
                feature({"type": "LineString", "coordinates": [[0, 0], [10, 10]]}),
                feature(
                    {
                        "type": "MultiLineString",
                        "coordinates": [[[0, 0], [1, 1]], [[2, 2], [3, 3]]],
                    }
                ),
                feature(
                    {
                        "type": "Polygon",
                        "coordinates": [
                            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                            [[2, 2], [4, 2], [4, 4], [2, 2]],
                        ],
                    }
                ),
                feature(
                    {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                            [[[5, 5], [6, 5], [6, 6], [5, 5]]],
                        ],
                    }
                ),
            ],
        }
        path = write_geojson(tmp_path / "all.geojson", data)

        result = GisLayerLoader().load(layer(path), str(path))

        assert result.crs == "EPSG:4326"
        assert result.crs_source == "file"
        assert result.feature_count == 6
        assert result.warnings == []
        kinds = [g.kind for g in result.geometries]
        assert kinds == ["point", "point", "line", "line", "polygon", "polygon"]

        point = result.geometries[0].parts[0][0]
        assert point == pytest.approx((lon_to_merc(-1.5), lat_to_merc(52.1)))
        # multi-part geometries stay a single geometry
        assert len(result.geometries[1].parts) == 2
        assert len(result.geometries[3].parts) == 2
        assert result.geometries[1].parts[1][0] == pytest.approx(
            (lon_to_merc(10), lat_to_merc(20))
        )
        # the polygon has a hole
        polygon = result.geometries[4]
        assert len(polygon.parts) == 2
        assert polygon.parts[0][2] == pytest.approx((lon_to_merc(10), lat_to_merc(10)))
        assert polygon.parts[1][0] == pytest.approx((lon_to_merc(2), lat_to_merc(2)))
        assert len(result.geometries[5].parts) == 2
        assert result.vertex_count == 1 + 2 + 2 + 4 + 5 + 4 + 4 + 4

    @pytest.mark.parametrize(
        "data",
        [
            {"type": "Point", "coordinates": [10, 20]},
            feature({"type": "Point", "coordinates": [10, 20]}),
            {
                "type": "GeometryCollection",
                "geometries": [{"type": "Point", "coordinates": [10, 20]}],
            },
        ],
    )
    def test_accepts_bare_geometries_and_features(self, tmp_path, data):
        path = write_geojson(tmp_path / "bare.geojson", data)
        result = GisLayerLoader().load(layer(path), str(path))
        assert result.geometries[0].parts[0][0] == pytest.approx(
            (lon_to_merc(10), lat_to_merc(20))
        )

    def test_altitude_is_ignored(self, tmp_path):
        path = write_geojson(
            tmp_path / "z.geojson",
            feature({"type": "Point", "coordinates": [10, 20, 350.5]}),
        )
        result = GisLayerLoader().load(layer(path), str(path))
        assert result.geometries[0].parts[0][0] == pytest.approx(
            (lon_to_merc(10), lat_to_merc(20))
        )

    def test_null_and_unsupported_geometries(self, tmp_path):
        path = write_geojson(
            tmp_path / "bad.geojson",
            {
                "type": "FeatureCollection",
                "features": [
                    feature(None),
                    feature({"type": "Point", "coordinates": [1, 1]}),
                    feature({"type": "Circle", "coordinates": [1, 1]}),
                ],
            },
        )
        result = GisLayerLoader().load(layer(path), str(path))
        assert len(result.geometries) == 1
        # the null geometry is not counted, the unsupported one is reported
        assert any("no supported geometry" in w for w in result.warnings)

    def test_unprojectable_and_degenerate_parts_are_dropped(self, tmp_path):
        """
        A line needs 2 vertices and a ring 3. Coordinates that cannot be
        converted, like infinity, are removed.
        """
        path = write_geojson(
            tmp_path / "degenerate.geojson",
            {
                "type": "FeatureCollection",
                "features": [
                    feature({"type": "LineString", "coordinates": [[1, 1]]}),
                    feature({"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}),
                    feature({"type": "LineString", "coordinates": [[0, 0], [2, 2]]}),
                ],
            },
        )
        result = GisLayerLoader().load(layer(path), str(path))
        assert len(result.geometries) == 1
        assert any("ignored" in w for w in result.warnings)

    def test_legacy_crs_member_is_honoured(self, tmp_path):
        """
        The coordinates are in Web Mercator already: they must not be converted.
        """
        path = write_geojson(
            tmp_path / "merc.geojson",
            {
                "type": "FeatureCollection",
                "crs": {
                    "type": "name",
                    "properties": {"name": "urn:ogc:def:crs:EPSG::3857"},
                },
                "features": [
                    feature({"type": "Point", "coordinates": [-166979.0, 6800000.0]})
                ],
            },
        )
        result = GisLayerLoader().load(layer(path), str(path))
        assert result.crs == "EPSG:3857"
        assert result.geometries[0].parts[0][0] == pytest.approx((-166979.0, 6800000.0))

    def test_crs84_urn_is_longitude_latitude(self, tmp_path):
        path = write_geojson(
            tmp_path / "crs84.geojson",
            {
                "type": "FeatureCollection",
                "crs": {
                    "type": "name",
                    "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
                },
                "features": [feature({"type": "Point", "coordinates": [10, 20]})],
            },
        )
        result = GisLayerLoader().load(layer(path), str(path))
        assert result.geometries[0].parts[0][0] == pytest.approx(
            (lon_to_merc(10), lat_to_merc(20))
        )

    def test_invalid_legacy_crs_falls_back_with_a_warning(self, tmp_path):
        path = write_geojson(
            tmp_path / "badcrs.geojson",
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "nonsense"}},
                "features": [feature({"type": "Point", "coordinates": [10, 20]})],
            },
        )
        result = GisLayerLoader().load(layer(path), str(path))
        assert result.crs == "EPSG:4326"
        assert any("not valid" in w for w in result.warnings)

    def test_layer_crs_overrides_the_file(self, tmp_path):
        path = write_geojson(
            tmp_path / "override.geojson",
            feature({"type": "Point", "coordinates": [500000, 5500000]}),
        )
        result = GisLayerLoader().load(layer(path, crs="EPSG:32630"), str(path))
        assert result.crs == "EPSG:32630"
        assert result.crs_source == "layer"
        # the easting 500000 of the UTM zone 30N is on its central meridian (-3 deg)
        assert result.geometries[0].parts[0][0][0] == pytest.approx(
            lon_to_merc(-3), abs=1e-3
        )

    def test_invalid_layer_crs_is_ignored_with_a_warning(self, tmp_path):
        path = write_geojson(
            tmp_path / "x.geojson", feature({"type": "Point", "coordinates": [10, 20]})
        )
        result = GisLayerLoader().load(layer(path, crs="EPSG:nope"), str(path))
        assert result.crs == "EPSG:4326"
        assert any("EPSG:nope" in w for w in result.warnings)

    @pytest.mark.parametrize(
        "content, message",
        [
            ("{not json", "not a valid GeoJSON"),
            ("[1, 2]", "not a valid GeoJSON object"),
            ('{"type": "Banana"}', "not supported"),
        ],
    )
    def test_invalid_files(self, tmp_path, content, message):
        path = tmp_path / "bad.geojson"
        path.write_text(content)
        with pytest.raises(GisLayerError, match=message):
            GisLayerLoader().load(layer(path), str(path))

    def test_missing_file(self, tmp_path):
        path = tmp_path / "missing.geojson"
        with pytest.raises(GisLayerError, match="does not exist"):
            GisLayerLoader().load(layer(path), str(path))

    def test_utf8_bom_is_accepted(self, tmp_path):
        path = tmp_path / "bom.geojson"
        path.write_bytes(
            b"\xef\xbb\xbf"
            + json.dumps(feature({"type": "Point", "coordinates": [1, 1]})).encode()
        )
        assert len(GisLayerLoader().load(layer(path), str(path)).geometries) == 1

    def test_too_large_layer(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pywr_editor.schematic.map.gis_overlay.MAX_VERTICES", 5)
        path = write_geojson(
            tmp_path / "large.geojson",
            feature({"type": "LineString", "coordinates": [[i, i] for i in range(10)]}),
        )
        with pytest.raises(GisLayerError, match="too large"):
            GisLayerLoader().load(layer(path), str(path))
        assert MAX_VERTICES > 5


def write_shapefile(
    base: Path,
    shape_type: int,
    geometries: list,
    prj: str | None = None,
) -> Path:
    """
    Creates a small Shapefile (.shp, .shx, .dbf and, optionally, .prj).
    """
    with shapefile.Writer(str(base), shapeType=shape_type) as writer:
        writer.field("name", "C")
        for index, geometry in enumerate(geometries):
            if shape_type == shapefile.POINT:
                writer.point(*geometry)
            elif shape_type == shapefile.POLYLINE:
                writer.line(geometry)
            else:
                writer.poly(geometry)
            writer.record(f"feature {index}")
    if prj is not None:
        base.with_suffix(".prj").write_text(prj)
    return base.with_suffix(".shp")


WGS84_WKT = pytest.importorskip("pyproj").CRS.from_epsg(4326).to_wkt()
UTM30N_WKT = pytest.importorskip("pyproj").CRS.from_epsg(32630).to_wkt()


class TestShapefileLoader:
    def test_points_with_prj(self, tmp_path):
        path = write_shapefile(
            tmp_path / "points", shapefile.POINT, [(-1.5, 52.1), (10, 20)], WGS84_WKT
        )
        result = GisLayerLoader().load(layer(path), str(path))

        assert result.crs == "EPSG:4326"
        assert result.crs_source == "file"
        assert result.warnings == []
        assert result.feature_count == 2
        assert result.geometries[0].parts[0][0] == pytest.approx(
            (lon_to_merc(-1.5), lat_to_merc(52.1))
        )

    def test_lines_and_polygons_with_a_projected_crs(self, tmp_path):
        """
        UTM zone 30N: the easting 500000 is on the central meridian (-3 deg).
        """
        line = write_shapefile(
            tmp_path / "line",
            shapefile.POLYLINE,
            [[[(500000, 5500000), (500000, 5600000)]]],
            UTM30N_WKT,
        )
        result = GisLayerLoader().load(layer(line), str(line))
        assert result.crs == "EPSG:32630"
        assert result.geometries[0].kind == "line"
        for x, _ in result.geometries[0].parts[0]:
            assert x == pytest.approx(lon_to_merc(-3), abs=1e-3)

        polygon = write_shapefile(
            tmp_path / "poly",
            shapefile.POLYGON,
            [[[(500000, 5500000), (510000, 5500000), (510000, 5510000)]]],
            UTM30N_WKT,
        )
        result = GisLayerLoader().load(layer(polygon), str(polygon))
        assert result.geometries[0].kind == "polygon"
        assert len(result.geometries[0].parts[0]) >= 3

    def test_missing_prj_assumes_the_map_crs_with_a_warning(self, tmp_path):
        path = write_shapefile(tmp_path / "noprj", shapefile.POINT, [(10, 20)])

        result = GisLayerLoader().load(layer(path), str(path))
        assert result.crs == "EPSG:4326"
        assert result.crs_source == "default"
        assert any(".prj" in w for w in result.warnings)
        assert result.geometries[0].parts[0][0] == pytest.approx(
            (lon_to_merc(10), lat_to_merc(20))
        )

        # the map CRS is used, not always 4326
        result = GisLayerLoader(default_crs="EPSG:32630").load(layer(path), str(path))
        assert result.crs == "EPSG:32630"

    def test_layer_crs_fixes_a_missing_prj_without_warning(self, tmp_path):
        path = write_shapefile(tmp_path / "noprj", shapefile.POINT, [(500000, 5500000)])

        result = GisLayerLoader().load(layer(path, crs="EPSG:32630"), str(path))
        assert result.crs_source == "layer"
        assert result.warnings == []
        assert result.geometries[0].parts[0][0][0] == pytest.approx(
            lon_to_merc(-3), abs=1e-3
        )

    def test_invalid_prj_is_ignored_with_a_warning(self, tmp_path):
        path = write_shapefile(
            tmp_path / "badprj", shapefile.POINT, [(10, 20)], "not wkt"
        )
        result = GisLayerLoader().load(layer(path), str(path))
        assert any("not valid" in w for w in result.warnings)

    def test_corrupted_shapefile(self, tmp_path):
        path = tmp_path / "broken.shp"
        path.write_bytes(b"this is not a shapefile")
        with pytest.raises(GisLayerError, match="not a valid Shapefile"):
            GisLayerLoader().load(layer(path), str(path))
