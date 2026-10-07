import weakref
from contextlib import contextmanager
from typing import Callable, Iterator, Literal

import shiboken6
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

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


class ThemeSignals(QObject):
    changed = Signal()
    """ Emitted after the theme changed and the registered widgets were refreshed """


class Theme:
    """
    Holds the active theme (light or dark) and the colours that do not belong to the
    Tailwind palette in Color.

    The theme can change while the editor is running. Stylesheets are strings built
    from Color and Theme values, so widgets that use colours must register their
    stylesheet builder with Theme.bind(), which applies it now and again on every theme
    change. Colours read while painting need no registration as widgets are repainted
    on change. Code that renders colours once (pixmaps, icons) can use
    Theme.on_change().
    """

    signals = ThemeSignals()
    """ Use signals.changed to listen to theme changes """

    _stylesheets: dict[int, tuple[weakref.ref, Callable[[QWidget], str]]] = {}
    _registrations: int = 0
    _callbacks: dict[tuple[int, int], tuple[weakref.ref, Callable[[QWidget], None]]] = (
        {}
    )

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
    def apply_mode(cls, mode: ThemeMode | str) -> None:
        """
        Changes the theme of the running application: sets the palette, rebuilds the
        registered stylesheets, runs the registered callbacks and repaints all the
        widgets.
        :param mode: "light" or "dark".
        :return: None
        """
        cls.set_mode(mode)
        app = QApplication.instance()
        if app is None:
            return
        app.setPalette(cls.palette())

        for registry in (cls._stylesheets, cls._callbacks):
            for key, (widget_ref, function) in list(registry.items()):
                widget = widget_ref()
                if widget is None or not shiboken6.isValid(widget):
                    registry.pop(key, None)
                    continue
                if registry is cls._stylesheets:
                    widget.setStyleSheet(function(widget))
                else:
                    function(widget)

        for widget in app.allWidgets():
            widget.update()
        cls.signals.changed.emit()

    @classmethod
    def prune(cls) -> None:
        """
        Drops the registrations of the widgets that were deleted.
        :return: None
        """
        for registry in (cls._stylesheets, cls._callbacks):
            for key, (widget_ref, _) in list(registry.items()):
                widget = widget_ref()
                if widget is None or not shiboken6.isValid(widget):
                    registry.pop(key, None)

    @classmethod
    def _register(
        cls, registry: dict, widget: QWidget, function: Callable, key: object
    ) -> None:
        """
        Registers a function for a widget without keeping the widget alive.
        :param registry: The registry to add the function to.
        :param widget: The widget.
        :param function: A function receiving the widget. It must not capture the
        widget (e.g. use "lambda w: w.stylesheet" instead of "lambda: self.stylesheet")
        :return: None
        """
        registry[key] = (weakref.ref(widget), function)
        # widgets are not tracked with signals or finalizers because connecting to
        # destroyed() crashes the interpreter at exit; dead widgets are dropped here
        cls._registrations += 1
        if cls._registrations % 200 == 0:
            cls.prune()

    @classmethod
    def bind(cls, widget: QWidget, builder: Callable[[QWidget], str]) -> None:
        """
        Sets the widget stylesheet and rebuilds it every time the theme changes.
        A widget has one builder: binding it again replaces the previous one.
        :param widget: The widget to style.
        :param builder: A function that receives the widget and returns the
        stylesheet for the active theme. It must not capture the widget.
        :return: None
        """
        widget.setStyleSheet(builder(widget))
        cls._register(cls._stylesheets, widget, builder, id(widget))

    @classmethod
    def on_change(cls, widget: QWidget, callback: Callable[[QWidget], None]) -> None:
        """
        Runs a callback every time the theme changes, for example to render again
        a pixmap or an icon. The callback is not run on registration.
        :param widget: The widget owning the callback. The callback is dropped when
        the widget is destroyed.
        :param callback: A function that receives the widget. It must not capture
        the widget.
        :return: None
        """
        cls._register(cls._callbacks, widget, callback, (id(widget), id(callback)))

    @classmethod
    @contextmanager
    def temporary_mode(cls, mode: ThemeMode) -> Iterator[None]:
        """
        Switches to a theme for the duration of the with block and restores the
        previous one afterwards, even on errors. Nothing happens if the theme is
        already active. The switch is synchronous, so the application is not painted
        with the temporary theme unless the event loop runs inside the block.
        :param mode: The theme to use inside the block.
        :return: None
        """
        previous = cls.mode
        if previous == mode:
            yield
            return

        cls.apply_mode(mode)
        try:
            yield
        finally:
            cls.apply_mode(previous)

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
