import logging
import sys
from argparse import ArgumentParser, BooleanOptionalAction

from PySide6.QtGui import QColor, QIcon, QPalette, Qt
from PySide6.QtWidgets import QApplication

from pywr_editor.dialogs import StartScreen
from pywr_editor.utils import ExceptionHandler, Logging, browse_files

from .main_window import MainWindow


def light_palette() -> QPalette:
    """
    Returns a light palette independent of the desktop theme. The application
    stylesheets hardcode light backgrounds, so a dark system palette (e.g. from a
    dark GTK theme on Linux) would render light text on light widgets.
    :return: The palette.
    """
    role = QPalette.ColorRole
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
    palette = QPalette()
    for color_role, color in colors.items():
        palette.setColor(color_role, QColor(color))

    disabled = QPalette.ColorGroup.Disabled
    for color_role in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(disabled, color_role, QColor("#a0a0a0"))
    return palette


# noinspection PyTypeChecker
def app() -> None:
    """
    Runs the application. This accepts the following arguments:
     * file: the path to the JSON file to open.
     * --create_new: force the editor to open an empty model.
     * --browse: open the editor with the file browser.
     * --log: enable logging.
     * --log_to_file: when supplied with --log, the editor activity is logged to a file
    :return: None
    """
    argument_parser = ArgumentParser(
        description="Open a new pywr model in the pywr editor"
    )

    argument_parser.add_argument("file", type=str, nargs="?")
    argument_parser.add_argument("--create_new", action=BooleanOptionalAction)
    argument_parser.add_argument("--browse", action=BooleanOptionalAction)
    argument_parser.add_argument("--log", action=BooleanOptionalAction)

    # register taskbar icon for Windows
    try:
        # noinspection PyUnresolvedReferences
        from ctypes import windll

        windll.shell32.SetCurrentProcessExplicitAppUserModelID("pywr-editor")
    except ImportError:
        pass

    # create the application
    options = argument_parser.parse_args()
    ExceptionHandler()
    editor = QApplication(sys.argv)
    editor.setWindowIcon(QIcon(":logos/small"))
    # the stylesheets assume a light theme; do not inherit a dark desktop palette
    editor.setStyle("Fusion")
    editor.setPalette(light_palette())

    # handle the logger
    Logging().configure(file_logging=options.log)
    if not options.log:
        Logging.disable()

    logger = logging.getLogger("main")
    logger.debug(f"Starting application with {sys.argv}")

    # show the welcome screen or the main window
    file = options.file if options.file else None
    create_new = options.create_new if options.create_new else None
    browse = options.browse if options.browse else None

    # enable dpi scale
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # create new model command
    if create_new is not None:
        logger.debug("Opening main window with empty model")
        MainWindow()
    # browse command
    elif browse is not None:
        logger.debug("Browsing for file")
        file = browse_files()
        if file:
            MainWindow(file)
    # file not provided, open the welcome screen
    elif file is None:
        logger.debug("Opening welcome screen")
        dialog = StartScreen()
        dialog.show()
    else:
        logger.debug(f"Opening main window with model file {file}")
        MainWindow(file)

    sys.exit(editor.exec())
