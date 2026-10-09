import math
from dataclasses import dataclass
from typing import Iterable, Sequence

MIN_SPAN_METRES = 1000.0
""" Smallest extent, in Web Mercator metres, fitted to the schematic. This stops a
single node (or nodes sharing a location) from zooming the map to an infinite scale """
FILL_RATIO = 0.7
""" The share of the schematic size that the geographic extent of the nodes fills """


@dataclass(frozen=True)
class GeoTransform:
    """
    Maps Web Mercator coordinates (metres) to scene coordinates (the schematic units)
    and back. Scene units cannot be Web Mercator metres: nodes are a few tens of units
    wide, so they would be invisible on a map spanning kilometres, and the content
    would be thousands of kilometres away from the schematic bounds. Instead, the
    transform is fitted to the nodes, so that the geographic view is displayed at a
    scale comparable to the schematic view. The y axis is flipped to match Qt's y-down
    convention (mirroring how Schematic.to_px() flips the pywr y axis).
    """

    centre_merc: tuple[float, float]
    """ The Web Mercator coordinate placed at the scene centre """
    centre_scene: tuple[float, float]
    """ The scene coordinate of the centre """
    metres_per_unit: float
    """ The number of Web Mercator metres in one scene unit """

    @classmethod
    def fit(
        cls,
        merc_points: Iterable[Sequence[float]],
        scene_size: Sequence[float],
    ) -> "GeoTransform":
        """
        Creates the transform that centres the points in the scene and fits them in
        FILL_RATIO of the scene size.
        :param merc_points: The (x, y) Web Mercator coordinates of the nodes. When
        empty, a transform centred on the origin with a 1 km extent is returned.
        :param scene_size: The (width, height) of the schematic.
        :return: The GeoTransform instance.
        """
        points = list(merc_points)
        if len(points) > 0:
            min_x = min(p[0] for p in points)
            max_x = max(p[0] for p in points)
            min_y = min(p[1] for p in points)
            max_y = max(p[1] for p in points)
        else:
            min_x = max_x = min_y = max_y = 0.0

        # a single scale is used on both axes to avoid distorting the map: the
        # larger extent, compared to the scene, drives it
        width = max(scene_size[0], 1) * FILL_RATIO
        height = max(scene_size[1], 1) * FILL_RATIO
        metres_per_unit = max(
            max(max_x - min_x, MIN_SPAN_METRES) / width,
            max(max_y - min_y, MIN_SPAN_METRES) / height,
        )

        return cls(
            centre_merc=((min_x + max_x) / 2, (min_y + max_y) / 2),
            centre_scene=(scene_size[0] / 2, scene_size[1] / 2),
            metres_per_unit=metres_per_unit,
        )

    def merc_to_scene(self, x: float, y: float) -> tuple[float, float]:
        """
        Converts Web Mercator coordinates to scene coordinates.
        :param x: The Web Mercator x coordinate (metres).
        :param y: The Web Mercator y coordinate (metres).
        :return: The (x, y) scene coordinates.
        """
        return (
            self.centre_scene[0] + (x - self.centre_merc[0]) / self.metres_per_unit,
            self.centre_scene[1] - (y - self.centre_merc[1]) / self.metres_per_unit,
        )

    def scene_to_merc(self, x: float, y: float) -> tuple[float, float]:
        """
        Converts scene coordinates to Web Mercator coordinates.
        :param x: The scene x coordinate.
        :param y: The scene y coordinate.
        :return: The (x, y) Web Mercator coordinates (metres).
        """
        return (
            self.centre_merc[0] + (x - self.centre_scene[0]) * self.metres_per_unit,
            self.centre_merc[1] - (y - self.centre_scene[1]) * self.metres_per_unit,
        )

    def metres_per_pixel(self, view_scale: float) -> float:
        """
        Returns the ground resolution on screen.
        :param view_scale: The view scale (screen pixels per scene unit).
        :return: The Web Mercator metres covered by one screen pixel.
        """
        return self.metres_per_unit / max(view_scale, 1e-12)

    @staticmethod
    def is_finite(point: Sequence[float]) -> bool:
        """
        Checks that a projected point can be placed on the schematic. pyproj returns
        infinity for the coordinates that cannot be projected.
        :param point: The coordinates.
        :return: True if all the values are finite.
        """
        return all(math.isfinite(value) for value in point)
