import pytest

from pywr_editor.schematic import Projector, is_valid_crs


class TestProjector:
    @pytest.mark.parametrize(
        "lon, lat",
        [
            # London
            (-0.448083, 51.6217),
            # a point near the antimeridian
            (179.9, -17.7),
            (-179.9, -17.7),
            # the origin
            (0, 0),
        ],
    )
    def test_round_trip(self, lon, lat):
        """
        Tests that converting a lon/lat pair to Web Mercator and back returns the
        original coordinates (within floating point tolerance).
        """
        projector = Projector("EPSG:4326")
        merc_x, merc_y = projector.lonlat_to_merc(lon, lat)
        back_lon, back_lat = projector.merc_to_lonlat(merc_x, merc_y)

        assert back_lon == pytest.approx(lon)
        assert back_lat == pytest.approx(lat)

    def test_known_point(self):
        """
        Tests the Web Mercator conversion against an independently-computed
        reference value for a known point (London).
        """
        projector = Projector("EPSG:4326")
        merc_x, merc_y = projector.lonlat_to_merc(-0.448083, 51.6217)

        assert merc_x == pytest.approx(-49880.37, abs=0.01)
        assert merc_y == pytest.approx(6732010.88, abs=0.01)

    def test_alternative_source_crs(self):
        """
        Tests that the Projector actually uses the given source CRS: the same raw
        input coordinates must produce different Web Mercator coordinates
        depending on which CRS they are declared in.
        """
        point = (400000, 400000)
        merc_from_4326 = Projector("EPSG:4326").lonlat_to_merc(*point)
        merc_from_27700 = Projector("EPSG:27700").lonlat_to_merc(*point)

        assert merc_from_4326 != pytest.approx(merc_from_27700)


@pytest.mark.parametrize(
    "crs, expected",
    [
        ("EPSG:4326", True),
        ("EPSG:27700", True),
        ("EPSG:3857", True),
        ("not-a-crs", False),
        ("", False),
    ],
)
def test_is_valid_crs(crs, expected):
    """
    Tests the is_valid_crs validation helper.
    """
    assert is_valid_crs(crs) == expected
