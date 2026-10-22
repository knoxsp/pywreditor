import json
from pathlib import Path
from typing import Tuple

import pytest
import shapefile
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QFileDialog, QMessageBox

from pywr_editor import MainWindow
from pywr_editor.dialogs import GisLayersDialog
from tests.utils import resolve_model_path


def write_geojson(path: Path, coordinates=(-1.5, 52.1)) -> Path:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "Point", "coordinates": list(coordinates)},
                    }
                ],
            }
        )
    )
    return path


class TestGisLayersDialog:
    model_file = resolve_model_path("model_geographic_positions.json")

    @pytest.fixture(scope="class")
    def window(self, qapp) -> MainWindow:
        """
        Creates a single window for all the tests, as the editor windows are heavy
        and the dialog tests must not create too many instances in one process.
        """
        window = MainWindow(self.model_file)
        # loading the model changes it: do not ask to save when the window is closed
        window.prompt_unsaved_changes = False
        window.show()
        yield window
        window.schematic.editor_settings.save_geo_view(False)
        window.close()
        window.deleteLater()

    @pytest.fixture
    def init_window(self, qtbot, window) -> Tuple[MainWindow, GisLayersDialog]:
        """
        Resets the layers and the view and opens a new dialog.
        """
        self.reset(window)
        dialog = GisLayersDialog(model_config=window.model_config, parent=window)
        dialog.show()
        yield window, dialog
        dialog.close()
        dialog.deleteLater()
        self.reset(window)

    @staticmethod
    def reset(window: MainWindow) -> None:
        """
        Removes the layers added by a test and leaves the geographic view.
        """
        window.model_config.map_config["layers"].clear()
        if window.schematic.editor_settings.is_geo_view_enabled:
            window.schematic.toggle_coordinate_system()
        else:
            window.schematic.refresh_gis_layers()

    @staticmethod
    def names(dialog: GisLayersDialog) -> list[str]:
        model = dialog.list_model
        return [model.index(r).data() for r in range(model.rowCount())]

    @staticmethod
    def add(monkeypatch, dialog: GisLayersDialog, *files: Path) -> None:
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileNames",
            lambda *args, **kwargs: ([str(f) for f in files], ""),
        )
        dialog.add_button.click()

    def test_empty_dialog(self, init_window):
        window, dialog = init_window
        assert dialog.windowTitle() == "GIS layers"
        assert dialog.list_model.rowCount() == 0
        assert dialog.form.isEnabled() is False
        assert dialog.remove_button.isEnabled() is False
        assert dialog.up_button.isEnabled() is False
        assert dialog.down_button.isEnabled() is False
        assert "Select a layer" in dialog.form.status.text()

    def test_add_layers(self, init_window, tmp_path, monkeypatch):
        window, dialog = init_window
        first = write_geojson(tmp_path / "first.geojson")
        second = write_geojson(tmp_path / "second.geojson")
        self.add(monkeypatch, dialog, first, second)

        layers = window.model_config.gis_layers.get_all()
        assert [layer.name for layer in layers] == ["first", "second"]
        assert layers[0].path == str(first)
        # the layer drawn on top (the last one) is first on the list, and selected
        assert self.names(dialog) == ["second", "first"]
        assert dialog.selected_layer_id() == layers[1].id
        assert dialog.form.isEnabled() is True
        assert dialog.form.name_field.text() == "second"
        assert dialog.form.path_field.text() == str(second)
        assert "1 feature(s)" in dialog.form.status.text()
        assert "EPSG:4326" in dialog.form.status.text()
        assert window.model_config.changed_ is True
        assert "Added 2 GIS layer(s)" in window.statusBar().currentMessage()

    def test_cancelled_file_picker_adds_nothing(self, init_window, monkeypatch):
        window, dialog = init_window
        self.add(monkeypatch, dialog)
        assert dialog.list_model.rowCount() == 0

    def test_selecting_a_layer_shows_it_in_the_form(
        self, init_window, tmp_path, monkeypatch
    ):
        window, dialog = init_window
        layers = window.model_config.gis_layers
        layers.add(str(write_geojson(tmp_path / "a.geojson")), name="Alpha")
        layers.add(str(write_geojson(tmp_path / "b.geojson")), name="Beta")
        layers.set_property(layers.get_all()[0].id, "stroke_width", 4.5)
        layers.set_property(layers.get_all()[0].id, "stroke_color", [1, 2, 3])
        dialog.list_model.reload()

        dialog.list.setCurrentIndex(dialog.list_model.index(1))  # Alpha
        assert dialog.form.name_field.text() == "Alpha"
        assert dialog.form.width_field.value() == 4.5
        assert dialog.form.stroke_button.color == QColor(1, 2, 3)
        assert dialog.remove_button.isEnabled() is True

    def test_edit_name(self, init_window, tmp_path, monkeypatch):
        window, dialog = init_window
        self.add(monkeypatch, dialog, write_geojson(tmp_path / "river.geojson"))
        layer_id = dialog.selected_layer_id()
        layers = window.model_config.gis_layers

        dialog.form.name_field.setText("Main river")
        dialog.form.name_field.editingFinished.emit()
        assert layers.find(layer_id).name == "Main river"
        assert self.names(dialog) == ["Main river"]
        assert dialog.form.title.text() == "Main river"

        # an empty name falls back to the file name
        dialog.form.name_field.setText("   ")
        dialog.form.name_field.editingFinished.emit()
        assert "name" not in layers.find(layer_id, as_dict=True)
        assert layers.find(layer_id).name == "river"

    def test_visibility_from_the_form_and_the_list(
        self, init_window, tmp_path, monkeypatch
    ):
        window, dialog = init_window
        self.add(monkeypatch, dialog, write_geojson(tmp_path / "a.geojson"))
        layer_id = dialog.selected_layer_id()
        layers = window.model_config.gis_layers
        window.schematic.toggle_coordinate_system()
        overlay = window.schematic.gis_overlay
        assert layer_id in overlay.groups

        dialog.form.visible_field.setChecked(False)
        assert layers.find(layer_id).visible is False
        assert layer_id not in overlay.groups
        index = dialog.list_model.index(0)
        assert index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked

        # from the check box on the list
        dialog.list_model.setData(
            index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
        )
        assert layers.find(layer_id).visible is True
        assert layer_id in overlay.groups
        assert dialog.form.visible_field.isChecked() is True

    def test_colours_and_width(self, init_window, tmp_path, monkeypatch):
        window, dialog = init_window
        self.add(monkeypatch, dialog, write_geojson(tmp_path / "a.geojson"))
        layer_id = dialog.selected_layer_id()
        layers = window.model_config.gis_layers

        monkeypatch.setattr(
            QColorDialog, "getColor", lambda *a, **k: QColor(10, 20, 30, 255)
        )
        dialog.form.stroke_button.click()
        assert layers.find(layer_id, as_dict=True)["stroke_color"] == [10, 20, 30]
        assert layers.find(layer_id).stroke_color == QColor(10, 20, 30)

        monkeypatch.setattr(
            QColorDialog, "getColor", lambda *a, **k: QColor(40, 50, 60, 70)
        )
        dialog.form.fill_button.click()
        assert layers.find(layer_id, as_dict=True)["fill_color"] == [40, 50, 60, 70]
        assert layers.find(layer_id).fill_color == QColor(40, 50, 60, 70)

        # a cancelled picker does not change the colour
        monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor())
        dialog.form.fill_button.click()
        assert layers.find(layer_id, as_dict=True)["fill_color"] == [40, 50, 60, 70]

        dialog.form.width_field.setValue(6)
        assert layers.find(layer_id).stroke_width == 6

    def test_style_changes_redraw_the_schematic(
        self, init_window, tmp_path, monkeypatch
    ):
        window, dialog = init_window
        window.schematic.toggle_coordinate_system()
        self.add(monkeypatch, dialog, write_geojson(tmp_path / "a.geojson"))
        layer_id = dialog.selected_layer_id()
        group = window.schematic.gis_overlay.groups[layer_id]

        monkeypatch.setattr(
            QColorDialog, "getColor", lambda *a, **k: QColor(9, 9, 9, 255)
        )
        dialog.form.stroke_button.click()
        new_group = window.schematic.gis_overlay.groups[layer_id]
        assert new_group is not group
        assert new_group.childItems()[0].color == QColor(9, 9, 9)

    def test_crs(self, init_window, tmp_path, monkeypatch):
        window, dialog = init_window
        self.add(
            monkeypatch, dialog, write_geojson(tmp_path / "a.geojson", (5e5, 55e5))
        )
        layer_id = dialog.selected_layer_id()
        layers = window.model_config.gis_layers

        dialog.form.crs_field.setText("not a crs")
        dialog.form.crs_field.editingFinished.emit()
        assert dialog.form.crs_message.isHidden() is False
        assert "not a valid CRS" in dialog.form.crs_message.text()
        assert layers.find(layer_id).crs is None

        dialog.form.crs_field.setText("EPSG:32630")
        dialog.form.crs_field.editingFinished.emit()
        assert dialog.form.crs_message.isHidden() is True
        assert layers.find(layer_id).crs == "EPSG:32630"
        assert "EPSG:32630" in dialog.form.status.text()
        assert "set above" in dialog.form.status.text()

        dialog.form.crs_field.setText("")
        dialog.form.crs_field.editingFinished.emit()
        assert layers.find(layer_id).crs is None
        assert "crs" not in layers.find(layer_id, as_dict=True)

    def test_browse_changes_the_file(self, init_window, tmp_path, monkeypatch):
        window, dialog = init_window
        self.add(monkeypatch, dialog, write_geojson(tmp_path / "a.geojson"))
        layer_id = dialog.selected_layer_id()
        other = write_geojson(tmp_path / "other.geojson")

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, **k: (str(other), "")
        )
        dialog.form.browse_button.click()
        assert window.model_config.gis_layers.find(layer_id).path == str(other)
        assert dialog.form.path_field.text() == str(other)

        # cancelling keeps the file
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
        dialog.form.browse_button.click()
        assert window.model_config.gis_layers.find(layer_id).path == str(other)

    def test_missing_file_and_shapefile_warning_are_shown(
        self, init_window, tmp_path, monkeypatch
    ):
        window, dialog = init_window
        self.add(monkeypatch, dialog, tmp_path / "missing.geojson")
        assert "does not exist" in dialog.form.status.text()

        base = tmp_path / "points"
        with shapefile.Writer(str(base), shapeType=shapefile.POINT) as writer:
            writer.field("name", "C")
            writer.point(1, 1)
            writer.record("a")
        self.add(monkeypatch, dialog, base.with_suffix(".shp"))
        assert ".prj" in dialog.form.status.text()

    def test_remove(self, init_window, tmp_path, monkeypatch):
        window, dialog = init_window
        self.add(
            monkeypatch,
            dialog,
            write_geojson(tmp_path / "a.geojson"),
            write_geojson(tmp_path / "b.geojson"),
        )
        layers = window.model_config.gis_layers

        # not confirmed
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
        )
        dialog.remove_button.click()
        assert len(layers.get_all()) == 2

        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        dialog.remove_button.click()
        assert [layer.name for layer in layers.get_all()] == ["a"]
        assert self.names(dialog) == ["a"]
        # the next layer is selected
        assert dialog.form.name_field.text() == "a"

        dialog.remove_button.click()
        assert layers.get_all() == []
        assert dialog.form.isEnabled() is False
        assert dialog.remove_button.isEnabled() is False

    def test_move(self, init_window, tmp_path, monkeypatch):
        window, dialog = init_window
        self.add(
            monkeypatch,
            dialog,
            write_geojson(tmp_path / "a.geojson"),
            write_geojson(tmp_path / "b.geojson"),
            write_geojson(tmp_path / "c.geojson"),
        )
        layers = window.model_config.gis_layers
        window.schematic.toggle_coordinate_system()

        # the list starts from the layer drawn on top
        assert self.names(dialog) == ["c", "b", "a"]
        # c is selected and on top: it cannot move up
        assert dialog.up_button.isEnabled() is False
        assert dialog.down_button.isEnabled() is True

        dialog.down_button.click()
        assert self.names(dialog) == ["b", "c", "a"]
        assert [layer.name for layer in layers.get_all()] == ["a", "c", "b"]
        assert dialog.form.name_field.text() == "c"
        groups = window.schematic.gis_overlay.groups
        by_name = {layers.find(i).name: g.zValue() for i, g in groups.items()}
        assert by_name["a"] < by_name["c"] < by_name["b"]

        dialog.down_button.click()
        assert self.names(dialog) == ["b", "a", "c"]
        assert dialog.down_button.isEnabled() is False

        dialog.up_button.click()
        dialog.up_button.click()
        assert self.names(dialog) == ["c", "b", "a"]
        assert dialog.up_button.isEnabled() is False

    def test_dialog_without_main_window(self, qtbot, tmp_path):
        """
        The dialog is usable on its own: the layer is read directly.
        """
        from pywr_editor.model import ModelConfig

        model = ModelConfig(self.model_file)
        model.gis_layers.add(str(write_geojson(tmp_path / "a.geojson")))
        dialog = GisLayersDialog(model_config=model)
        qtbot.addWidget(dialog)
        dialog.show()

        assert dialog.schematic is None
        assert "1 feature(s)" in dialog.form.status.text()
        dialog.form.visible_field.setChecked(False)  # no schematic to update
        dialog.show_message("ignored")

    def test_action_opens_the_dialog(self, init_window, qtbot):
        window, _ = init_window
        action = window.app_actions.get("manage-gis-layers")
        assert action.text() == "GIS layers"
        assert action.icon().isNull() is False

        before = len(window.findChildren(GisLayersDialog))
        action.trigger()
        dialogs = window.findChildren(GisLayersDialog)
        assert len(dialogs) == before + 1
        assert dialogs[-1].isVisible() is True
        # the button is in the schematic tab
        panel = window.toolbar.tabs["Schematic"].panels["Misc"]
        assert action.text() in panel.buttons
