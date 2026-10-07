from typing import Literal

from PySide6.QtGui import QColor, QPalette

ThemeMode = Literal["light", "dark"]

# the dark theme mirrors the Tailwind shade scale used by Color: a light shade is
# replaced with the opposite shade (e.g. 100 becomes 800) so that text, borders
# and hover states keep their relative contrast. Shade 80 is the window background
SHADE_MIRROR = {
    50: 900,
    80: 800,
    100: 800,
    200: 700,
    300: 600,
    400: 500,
    500: 400,
    600: 300,
    700: 200,
    800: 100,
    900: 50,
}


class Theme:
    """
    Holds the active theme (light or dark) and the colours that do not belong to the
    Tailwind palette in Color. Set the mode with Theme.set_mode() before any widget is
    created: stylesheets are generated when widgets are initialised.
    """

    mode: ThemeMode = "light"
    """ The active theme """

    tokens: dict[str, tuple[str, str]] = {
        # token: (light colour, dark colour)
        "base": ("#FFFFFF", "#111827"),
        "window": ("#F0F0F0", "#1f2937"),
        "border": ("#CCCCCC", "#4b5563"),
        "border-strong": ("#BBBBBB", "#6b7280"),
        "text": ("#000000", "#f3f4f6"),
        "text-inverse": ("#FFFFFF", "#111827"),
    }
    """ Semantic colours as (light, dark) pairs """

    @classmethod
    def set_mode(cls, mode: ThemeMode | str) -> None:
        """
        Sets the theme.
        :param mode: "light" or "dark". Any other value falls back to light.
        :return: None
        """
        cls.mode = "dark" if mode == "dark" else "light"

    @classmethod
    def is_dark(cls) -> bool:
        """
        Whether the dark theme is active.
        :return: True if the theme is dark.
        """
        return cls.mode == "dark"

    @classmethod
    def shade(cls, shade: int | str) -> int | str:
        """
        Converts a light-theme Tailwind shade to the active theme.
        :param shade: The shade as defined for the light theme.
        :return: The shade to use.
        """
        if cls.is_dark():
            return SHADE_MIRROR.get(shade, shade)
        return shade

    @classmethod
    def color(cls, token: str) -> str:
        """
        Returns a semantic colour for the active theme.
        :param token: The key in Theme.tokens.
        :return: The hex colour.
        """
        light, dark = cls.tokens[token]
        return dark if cls.is_dark() else light

    @classmethod
    def overlay(cls, alpha: int) -> str:
        """
        Returns a translucent colour that darkens a light background or lightens
        a dark one.
        :param alpha: The alpha channel (0-255).
        :return: The colour as rgba() string.
        """
        channel = 255 if cls.is_dark() else 0
        return f"rgba({channel}, {channel}, {channel}, {alpha})"

    @classmethod
    def palette(cls) -> QPalette:
        """
        Returns an application palette independent of the desktop theme. The
        stylesheets only style some widgets, so the others need explicit colours.
        :return: The palette.
        """
        role = QPalette.ColorRole
        if cls.is_dark():
            colors = {
                role.Window: "#1f2937",
                role.WindowText: "#f3f4f6",
                role.Base: "#111827",
                role.AlternateBase: "#1f2937",
                role.ToolTipBase: "#374151",
                role.ToolTipText: "#f3f4f6",
                role.PlaceholderText: "#9ca3af",
                role.Text: "#f3f4f6",
                role.Button: "#374151",
                role.ButtonText: "#f3f4f6",
                role.BrightText: "#ffffff",
                role.Light: "#4b5563",
                role.Midlight: "#374151",
                role.Mid: "#4b5563",
                role.Dark: "#111827",
                role.Shadow: "#000000",
                role.Highlight: "#2563eb",
                role.HighlightedText: "#ffffff",
                role.Link: "#60a5fa",
                role.LinkVisited: "#c084fc",
            }
            disabled_color = "#6b7280"
        else:
            colors = {
                role.Window: "#f0f0f0",
                role.WindowText: "#000000",
                role.Base: "#ffffff",
                role.AlternateBase: "#f5f5f5",
                role.ToolTipBase: "#ffffdc",
                role.ToolTipText: "#000000",
                role.PlaceholderText: "#808080",
                role.Text: "#000000",
                role.Button: "#f0f0f0",
                role.ButtonText: "#000000",
                role.BrightText: "#ffffff",
                role.Light: "#ffffff",
                role.Midlight: "#e3e3e3",
                role.Mid: "#a0a0a0",
                role.Dark: "#a0a0a0",
                role.Shadow: "#696969",
                role.Highlight: "#0078d7",
                role.HighlightedText: "#ffffff",
                role.Link: "#0000ff",
                role.LinkVisited: "#ff00ff",
            }
            disabled_color = "#a0a0a0"

        palette = QPalette()
        for color_role, color in colors.items():
            palette.setColor(color_role, QColor(color))

        disabled = QPalette.ColorGroup.Disabled
        for color_role in (role.WindowText, role.Text, role.ButtonText):
            palette.setColor(disabled, color_role, QColor(disabled_color))
        return palette
