from PySide6.QtCore import QByteArray, QFile, QSize, Qt, QTextStream
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import Theme

"""
Single entry point to load the icons stored in the Qt resources, so that they can
follow the theme. The SVG icons currently look the same in both themes, so nothing is
registered below. When they need to change, add entries to one of these mappings
without touching the code that loads the icons:
 * DARK_ICONS maps a resource path (e.g. ":toolbar/open") to a dedicated icon file
   or resource to use in the dark theme.
 * DARK_SVG_COLORS maps a colour found in the SVG data of an icon to the colour to
   replace it with in the dark theme. The key is the resource path or "*" to apply the
   colours to every SVG icon.
Icons are refreshed on theme change with refresh_icons() or Theme.on_change().
"""

DARK_ICONS: dict[str, str] = {}
""" Resource path of a light icon: path of the icon to use in the dark theme """
DARK_SVG_COLORS: dict[str, dict[str, str]] = {}
""" Resource path (or "*"): {light colour: dark colour} replaced in the SVG data """


def _read_resource(resource: str) -> str:
    """
    Reads a text resource.
    :param resource: The resource path.
    :return: The file content.
    """
    file = QFile(resource)
    file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text)
    content = QTextStream(file).readAll()
    file.close()
    return content


def _recolored_svg_icon(resource: str, colors: dict[str, str]) -> QIcon:
    """
    Renders an SVG icon after replacing its colours.
    :param resource: The SVG resource path.
    :param colors: The {old colour: new colour} mapping.
    :return: The icon.
    """
    svg = _read_resource(resource)
    for old_color, new_color in colors.items():
        svg = svg.replace(old_color, new_color)

    renderer = QSvgRenderer(QByteArray(svg.encode()))
    size = renderer.defaultSize()
    if not size.isValid() or size.isEmpty():
        size = QSize(64, 64)
    pixmap = QPixmap(size * 4)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def themed_icon(resource: str) -> QIcon:
    """
    Returns the icon for the active theme.
    :param resource: The resource path (e.g. ":toolbar/open"). An empty string
    returns an empty icon.
    :return: The QIcon instance.
    """
    if not resource or not Theme.is_dark():
        return QIcon(resource)

    if resource in DARK_ICONS:
        return QIcon(DARK_ICONS[resource])

    colors = {**DARK_SVG_COLORS.get("*", {}), **DARK_SVG_COLORS.get(resource, {})}
    if len(colors) > 0:
        return _recolored_svg_icon(resource, colors)
    return QIcon(resource)
