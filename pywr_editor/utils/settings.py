import hashlib
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import QPointF, QSettings

from pywr_editor.model import ModelFileInfo

if TYPE_CHECKING:
    from pywr_editor import MainWindow


class Settings:
    json_file = None
    lock_key = "schematic/lock"
    hide_labels_key = "schematic/hide_labels"
    hide_arrows_key = "schematic/hide_arrows"
    hide_legend_key = "schematic/hide_legend"
    hidden_node_types_key = "schematic/hidden_node_types"
    zoom_level_key = "schematic/zoom_level"
    schematic_center_key = "schematic/schematic_center"
    reverse_zoom_key = "schematic/reverse_zoom"
    legend_position_key = "schematic/legend_position"
    recent_projects_key = "recent_projects"
    run_to_date_key = "run_to_date"

    def __init__(self, json_file: str | None = None):
        """
        Initialises the class.
        :param json_file: The path to the JSON file.
        :return: None
        """
        self.json_file = json_file
        self.org_name = "pywr-editor"
        self.app_name = None

        # store the information per file/model
        if self.json_file is not None:
            self.instance.setValue("file", self.json_file)
            self.app_name = hashlib.md5(self.json_file.encode()).hexdigest()

        self.store_geometry_widget = [
            "toolbar",
            "splitter",
            "components_tree",
            "schematic",
        ]

    @property
    def instance(self) -> QSettings:
        """
        Returns the settings instance.
        :returns The QSettings object.
        """
        return QSettings(self.org_name, self.app_name)

    @property
    def global_instance(self) -> QSettings:
        """
        Returns the settings instance. This is not connected to the model file.
        :returns The QSettings object.
        """
        return QSettings(self.org_name)

    def save_window_attributes(self, window: "MainWindow") -> None:
        """
        Saves the window and widget's geometry and state.
        :param window: The window instance.
        :return: None
        """
        if self.app_name is None:
            return

        qsettings = self.instance

        qsettings.setValue("window/geometry", window.saveGeometry())
        qsettings.setValue("window/state", window.saveState())
        for widget in self.store_geometry_widget:
            w = getattr(window, widget)
            qsettings.setValue(f"{widget}/geometry", w.saveGeometry())
            if hasattr(w, "saveState"):
                qsettings.setValue(f"{widget}/state", w.saveState())

    def restore_window_attributes(self, window: "MainWindow") -> None:
        """
        Restores the  window and widget's geometry and state.
        :param window: The window instance.
        :return: None
        """
        if self.app_name is None:
            return

        qsettings = self.instance

        window.restoreGeometry(qsettings.value("window/geometry"))
        window.restoreState(qsettings.value("window/state"))
        for widget in self.store_geometry_widget:
            w = getattr(window, widget)
            w.restoreGeometry(qsettings.value(f"{widget}/geometry"))
            if hasattr(w, "restoreState"):
                w.restoreState(qsettings.value(f"{widget}/state"))

    @property
    def is_schematic_locked(self) -> bool:
        """
        Returns the schematic lock status.
        :return: True if the schematic is locked, False otherwise.
        """
        return self.str_to_bool(self.instance.value(self.lock_key, defaultValue=False))

    def save_schematic_lock(self, lock: bool) -> None:
        """
        Sets the schematic lock status.
        :return: None.
        """
        if self.app_name is None:
            return
        self.instance.setValue(self.lock_key, lock)

    @property
    def are_labels_hidden(self) -> bool:
        """
        Whether the schematic labels should be hidden.
        :return: True if the schematic label are hidden, False otherwise.
        """
        return self.str_to_bool(
            self.instance.value(self.hide_labels_key, defaultValue=False)
        )

    def save_hide_labels(self, hide: bool) -> None:
        """
        Sets the display status of the schematic labels.
        :param hide: True to hide the labels, False otherwise.
        :return: None.
        """
        if self.app_name is None:
            return
        self.instance.setValue(self.hide_labels_key, hide)

    @property
    def run_to_date(self) -> bool:
        """
        Returns the run to date.
        :return: The date as string
        """
        return self.instance.value(self.run_to_date_key)

    def save_run_to_date(self, date: str) -> None:
        """
        Stores the run to date for a model.
        :param date: The date as string.
        :return: None.
        """
        if self.app_name is None and not isinstance(date, str):
            return
        self.instance.setValue(self.run_to_date_key, date)

    @property
    def are_edge_arrows_hidden(self) -> bool:
        """
        Whether the schematic edge arrows should be hidden.
        :return: True if the schematic arrows are hidden, False otherwise.
        """
        return self.str_to_bool(
            self.instance.value(self.hide_arrows_key, defaultValue=False)
        )

    def save_hide_arrows(self, hide: bool) -> None:
        """
        Sets the display status of the schematic edge arrows.
        :param hide: True to hide the edge arrows, False otherwise.
        :return: None.
        """
        if self.app_name is None:
            return
        self.instance.setValue(self.hide_arrows_key, hide)

    @property
    def are_legend_hidden(self) -> bool:
        """
        Whether the schematic legend should be hidden.
        :return: True if the schematic legend is hidden, False otherwise.
        """
        return self.str_to_bool(
            self.instance.value(self.hide_legend_key, defaultValue=False)
        )

    def save_hide_legend(self, hide: bool) -> None:
        """
        Sets the display status of the schematic legend.
        :param hide: True to hide the legend, False otherwise.
        :return: None.
        """
        if self.app_name is None:
            return
        self.instance.setValue(self.hide_legend_key, hide)

    @property
    def hidden_node_types(self) -> list[str]:
        """
        Returns the list of node types currently hidden on the schematic.
        :return: The list of node type keys. Empty if none are hidden.
        """
        raw_value = self.instance.value(self.hidden_node_types_key, defaultValue="[]")
        try:
            node_types = json.loads(raw_value)
        except (TypeError, ValueError):
            return []
        if not isinstance(node_types, list):
            return []
        return node_types

    def save_hidden_node_types(self, node_types: list[str]) -> None:
        """
        Stores the list of node types currently hidden on the schematic.
        :param node_types: The list of node type keys to store.
        :return: None.
        """
        if self.app_name is None:
            return
        self.instance.setValue(self.hidden_node_types_key, json.dumps(node_types))

    @property
    def zoom_level(self) -> float:
        """
        Returns the schematic zoom level.
        :return: None
        """
        return float(self.instance.value(self.zoom_level_key, defaultValue=1))

    def save_zoom_level(self, zoom_level: float) -> None:
        """
        Stores the schematic zoom level.
        :param zoom_level: The zoom level
        :return: None
        """
        if self.app_name is None:
            return
        self.instance.setValue(self.zoom_level_key, zoom_level)

    @property
    def schematic_center(self) -> QPointF:
        """
        Returns the schematic centre.
        :return: None
        """
        return self.instance.value(self.schematic_center_key)

    def save_schematic_center(self, position: list[QPointF] | list[QPointF]) -> None:
        """
        Stores the schematic zoom level.
        :param position: The schematic centre as list or tuple of QPointF.
        :return: None
        """
        if self.app_name is None:
            return
        self.instance.setValue(self.schematic_center_key, position)

    @property
    def is_zoom_reversed(self) -> bool:
        """
        Whether the scroll-wheel zoom direction is reversed.
        :return: True if the zoom direction is reversed, False otherwise.
        """
        return self.str_to_bool(
            self.instance.value(self.reverse_zoom_key, defaultValue=False)
        )

    def save_reverse_zoom(self, reverse: bool) -> None:
        """
        Sets whether the scroll-wheel zoom direction is reversed.
        :param reverse: True to reverse the zoom direction, False otherwise.
        :return: None.
        """
        if self.app_name is None:
            return
        self.instance.setValue(self.reverse_zoom_key, reverse)

    @property
    def legend_position(self) -> Literal["left", "right"]:
        """
        Returns the schematic legend's horizontal position.
        :return: "left" or "right". Defaults to "left".
        """
        position = self.instance.value(self.legend_position_key, defaultValue="left")
        return position if position in ("left", "right") else "left"

    def save_legend_position(self, position: Literal["left", "right"]) -> None:
        """
        Stores the schematic legend's horizontal position.
        :param position: "left" or "right".
        :return: None.
        """
        if self.app_name is None:
            return
        self.instance.setValue(self.legend_position_key, position)

    def _get_recent_files_list(self) -> list[str]:
        """
        Returns the stored recent-file paths as a proper list. QSettings' INI
        backend serialises a single-item list the same way as a plain string,
        so a 1-entry list is read back as a bare str rather than a list of one
        - this normalises both that case and the unset (None) case.
        :return: The list of recent file paths (empty if none are stored).
        """
        recent_files = self.global_instance.value(self.recent_projects_key)
        if recent_files is None:
            return []
        if isinstance(recent_files, str):
            return [recent_files]
        return recent_files

    def get_recent_files(self) -> list[dict[str, str | ModelFileInfo]]:
        """
        Returns the list of recent open files.
        :return: The files as dictionary or an empty list if no file has been stored.
        """
        recent_files = self._get_recent_files_list()
        valid_files = []
        file_info = []

        if recent_files is not None:
            for json_file in recent_files:
                json_file = os.path.normpath(json_file)

                # remove non-existing files
                if not os.path.exists(json_file):
                    continue
                # collect file information
                # noinspection PyBroadException
                try:
                    with open(json_file, "r") as file:
                        content = json.load(file)
                        if "metadata" in content and "title" in content["metadata"]:
                            file_info.append(
                                {
                                    "file": json_file,
                                    "title": content["metadata"]["title"],
                                    "last_updated": ModelFileInfo(
                                        json_file
                                    ).last_modified_on,
                                    "last_updated_obj": datetime.strptime(
                                        ModelFileInfo(json_file).last_modified_on,
                                        "%d-%m-%Y %H:%M",
                                    ),
                                }
                            )
                            valid_files.append(json_file)
                except Exception:
                    pass

        # store only existing and non-duplicated files
        self.global_instance.setValue(self.recent_projects_key, list(set(valid_files)))

        return sorted(file_info, key=lambda d: d["last_updated_obj"], reverse=True)

    def save_recent_file(self, file: str) -> None:
        """
        Stores a new file in the recent file list.
        :return: None.
        """
        # this is not connected to any model file
        recent_files = self._get_recent_files_list()

        if file not in recent_files:
            recent_files.append(file)

        self.global_instance.setValue(self.recent_projects_key, recent_files)

    def clear_recent_files(self) -> None:
        """
        Clears the list of recent files.
        :return: None
        """
        self.global_instance.setValue(self.recent_projects_key, [])

    @staticmethod
    def str_to_bool(value: str) -> bool:
        """
        Converts a string to boolean. QSettings stores python boolean as lowercase
        strings.
        :param value: The value to convert.
        :return: The string as boolean.
        """
        return value.lower() == "true" if isinstance(value, str) else bool(value)
