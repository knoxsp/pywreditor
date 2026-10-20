import copy
import json

import pyproj
import pytest
from PySide6.QtCore import QTimer

from pywr_editor import MainWindow
from pywr_editor.toolbar import MapSettings
from tests.utils import close_message_box, resolve_model_path

BASE_MODEL = resolve_model_path("model_geographic_positions.json")


class TestMapSettings:
    @pytest.fixture(autouse=True)
    def init_window(self, qtbot, tmp_path):
        """
        Opens a copy of the geographic model.
        """
        with open(BASE_MODEL) as fp:
            model = json.load(fp)
        path = tmp_path / "model.json"
        path.write_text(json.dumps(model))
        QTimer.singleShot(100, close_message_box)
        self.window = MainWindow(str(path))
        self.window.hide()
        self.schematic = self.window.schematic
        self.panel: MapSettings = self.window.map_settings
        self.config = self.window.model_config
        self.initial = copy.deepcopy(self.config.json)
        yield

    def test_panel_is_in_the_settings_tab(self):
        settings_tab = self.window.toolbar.tabs["Settings"]
        assert "Schematic -> Map" in settings_tab.panels
        assert self.panel.geo_view.isChecked() is False
        assert self.panel.basemap.isChecked() is True
        assert self.panel.crs_field.text() == "EPSG:4326"
        assert "WGS 84" in self.panel.crs_message.text()
        assert self.panel.layers_label.text() == "No layers"

    def test_geo_view_switch_and_toolbar_button_stay_in_sync(self):
        action = self.window.app_actions.get("toggle-geo-view")

        self.panel.geo_view.setChecked(True)
        assert self.window.editor_settings.is_geo_view_enabled is True
        assert action.isChecked() is True

        action.trigger()
        assert self.window.editor_settings.is_geo_view_enabled is False
        assert self.panel.geo_view.isChecked() is False

        self.schematic.set_geo_view(True)
        assert self.panel.geo_view.isChecked() is True
        assert action.isChecked() is True

    def test_switch_is_reset_when_the_view_cannot_change(self):
        self.window.is_model_running = True
        self.panel.geo_view.setChecked(True)
        assert self.window.editor_settings.is_geo_view_enabled is False
        assert self.panel.geo_view.isChecked() is False
        self.window.is_model_running = False

    def test_basemap_switch_is_saved_in_the_model(self):
        self.schematic.set_geo_view(True)
        self.panel.basemap.setChecked(False)
        assert self.config.map_config["show_basemap"] is False
        assert self.schematic.tile_layer.is_active is False
        assert self.schematic.attribution.isHidden() is True
        assert self.config.json != self.initial

        self.panel.basemap.setChecked(True)
        assert self.config.map_config["show_basemap"] is True

    def test_invalid_crs_is_rejected(self):
        self.panel.crs_field.setText("not a crs")
        self.panel.crs_field.editingFinished.emit()
        assert "not a valid CRS" in self.panel.crs_message.text()
        assert self.config.map_config.get("crs") == "EPSG:4326"
        assert "map" not in self.config.editor_config

    def test_empty_crs_restores_the_saved_one(self):
        self.panel.crs_field.setText("  ")
        self.panel.crs_field.editingFinished.emit()
        assert self.panel.crs_field.text() == "EPSG:4326"

    def test_unchanged_crs_is_not_saved(self):
        self.panel.crs_field.editingFinished.emit()
        assert "map" not in self.config.editor_config

    def test_valid_crs_is_saved_and_nodes_are_plotted_again(self):
        """
        Converting the positions to British National Grid and setting the CRS
        places the nodes where they were, compared with pyproj.
        """
        self.schematic.set_geo_view(True)
        before = {
            name: node.pos().toTuple()
            for name, node in self.schematic.node_items.items()
        }
        to_bng = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
        for name in ["Reservoir", "Link1"]:
            lonlat = self.config.nodes.config(name, as_dict=False).geographic_position
            self.config.nodes.set_geographic_position(
                list(to_bng.transform(*lonlat)), node_name=name
            )

        self.panel.crs_field.setText("EPSG:27700")
        self.panel.crs_field.editingFinished.emit()

        assert self.config.geographic_crs == "EPSG:27700"
        assert self.config.has_changes is True
        assert "British National Grid" in self.panel.crs_message.text()
        assert "outside" not in self.panel.crs_message.text()
        for name in ["Reservoir", "Link1"]:
            assert self.schematic.node_items[name].pos().toTuple() == pytest.approx(
                before[name], abs=1.0
            )

    def test_degrees_with_a_projected_crs_show_a_hint(self):
        self.panel.crs_field.setText("EPSG:27700")
        self.panel.crs_field.editingFinished.emit()
        assert "look like longitudes and latitudes" in self.panel.crs_message.text()

    def test_layers_button_and_label(self, tmp_path):
        opened = []
        self.window.open_gis_layers_dialog = lambda: opened.append(1)
        action = self.window.app_actions.get("manage-gis-layers")
        action.triggered.disconnect()
        action.triggered.connect(lambda: opened.append(1))
        self.panel.layers_button.click()
        assert opened == [1]

        path = tmp_path / "a.geojson"
        path.write_text(json.dumps({"type": "Point", "coordinates": [1, 1]}))
        first = self.config.gis_layers.add(str(path))
        self.config.gis_layers.add(str(path))
        self.config.gis_layers.set_visible(first["id"], False)
        self.schematic.refresh_gis_layers()
        assert self.panel.layers_label.text() == "2 layers (1 shown)"

    def test_layers_button_follows_the_action(self):
        action = self.window.app_actions.get("manage-gis-layers")
        action.setDisabled(True)
        assert self.panel.layers_button.isEnabled() is False
        action.setDisabled(False)
        assert self.panel.layers_button.isEnabled() is True


class TestCrsSuggestion:
    def test_suggests_the_crs_fitting_the_positions(self, qtbot, tmp_path):
        """
        Tests that British National Grid positions in a model using the default CRS
        produce a warning suggesting EPSG:27700.
        """
        with open(BASE_MODEL) as fp:
            model = json.load(fp)
        for node in model["nodes"]:
            if "position" in node and "geographic" in node["position"]:
                node["position"]["geographic"] = [530000.0, 180000.0]
        path = tmp_path / "model.json"
        path.write_text(json.dumps(model))
        QTimer.singleShot(100, close_message_box)
        window = MainWindow(str(path))
        window.hide()

        warnings = window.schematic.crs_warnings()
        assert any("fit EPSG:27700" in warning for warning in warnings)

        window.model_config.update_geographic_crs("EPSG:27700")
        window.schematic.rebuild_geo_projector()
        assert not any("fit EPSG" in w for w in window.schematic.crs_warnings())


class TestCrsPersistence:
    def test_crs_is_saved_and_close_can_be_cancelled(self, qtbot, tmp_path):
        with open(BASE_MODEL) as fp:
            model = json.load(fp)
        path = tmp_path / "model.json"
        path.write_text(json.dumps(model))
        QTimer.singleShot(100, close_message_box)
        window = MainWindow(str(path))
        window.show()
        window.map_settings.crs_field.setText("EPSG:27700")
        window.map_settings.on_crs_edited()
        assert window.model_config.has_changes

        # cancelling the "unsaved changes" prompt keeps the window open
        window.maybe_save = lambda: False
        assert window.close() is False
        assert window.isVisible()

        window.model_config.save()
        assert json.loads(path.read_text())["metadata"]["crs"] == "EPSG:27700"
        window.prompt_unsaved_changes = False
        window.model_config.reset_change_flag()
        window.close()
