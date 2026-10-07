from typing import Literal

import qtawesome as qta
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, Qt
from PySide6.QtWidgets import QPushButton, QSizePolicy

from pywr_editor.style import Color, Theme, stylesheet_dict_to_str


class PushIconButton(QPushButton):
    def __init__(
        self,
        icon: str | QIcon,
        icon_size=None,
        label: str = "",
        small: bool = False,
        accent: bool = False,
        position: Literal["left", "right"] = "left",
        parent=None,
    ):
        """
        Renders a QPUshButton with an icon.
        :param icon: The icon path or QIcon instance.
        :param label: The button label. Optional.
        :param icon_size: The size of the icon. Default to QSize(16, 16).
        :param position: The icon position (left or right). Default to left.
        :param small: Whether to reduce the x-padding size. Default to False.
        :param parent: The parent widget. Optional.
        """
        super().__init__(parent=parent)

        self.accent = accent
        self.small = small
        self.icon_path = icon if isinstance(icon, str) else None
        if isinstance(icon, str):
            icon = self.get_icon(icon, accent)

        self.setText(label)
        self.setIcon(icon)
        if icon_size is None:
            icon_size = QSize(16, 16)
        self.setIconSize(icon_size)

        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        if position == "right":
            self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        Theme.bind(self, lambda w: w.stylesheet)
        if self.icon_path is not None and "msc." in self.icon_path:
            Theme.on_change(
                self, lambda w: w.setIcon(w.get_icon(w.icon_path, w.accent))
            )

    @staticmethod
    def get_icon(icon: str, accent: bool) -> QIcon:
        """
        Loads the icon from a path or a qtawesome name.
        :param icon: The icon path or name.
        :param accent: Whether the button is an accent button.
        :return: The icon.
        """
        if "msc." in icon:
            props = (
                dict(
                    color="white",
                    color_active="white",
                    color_disabled=Color("gray", 300).hex,
                )
                if accent
                else {}
            )
            return qta.icon(icon, **props)
        return QIcon(icon)

    @property
    def stylesheet(self) -> str:
        """
        Returns the stylesheet.
        :return: The stylesheet as string.
        """
        stylesheet = {"padding": "3px 4px" if self.small else "5px 5px"}
        if self.accent:
            stylesheet["color"] = "white"
            stylesheet["background"] = Color("blue", 500).hex
            stylesheet["border-color"] = Color("blue", 600).hex
            stylesheet[":hover"] = {
                "background": Color("blue", 600).hex,
                "border": f"1px solid {Color('blue', 600).hex}",
            }
            stylesheet[":disabled"] = {
                "background": Color("gray", 100).hex,
                "border": f"1px solid {Color('gray', 300).hex}",
                "color": Color("gray", 300).hex,
            }
        return stylesheet_dict_to_str({"PushIconButton": stylesheet})
