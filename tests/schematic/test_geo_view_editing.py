import copy
import json
import math

import pyproj
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGraphicsItem

from pywr_editor import MainWindow
from pywr_editor.schematic import Schematic
from pywr_editor.schematic.commands.move_item_command import MoveItemCommand
from pywr_editor.schematic.map import europe_extent_merc
from tests.utils import close_message_box, resolve_model_path

BASE_MODEL = resolve_model_path("model_geographic_positions.json")


def model_with(tmp_path, editor_config=None, geographic=None, **node_updates):
    """
    Writes a copy of the geographic model with changes.
    :param tmp_path: The directory where to write the model.
    :param editor_config: The "pywr_editor" dictionary to add to the model.
    :param geographic: A dictionary with the node name and the "geographic" value to
    set (None removes the key).
    :return: The path to the model file.
    """
    with open(BASE_MODEL) as fp:
        model = json.load(fp)
    for node in model["nodes"]:
        if geographic is not None and node["name"] in geographic:
            value = geographic[node["name"]]
            if value is None:
                node["position"].pop("geographic", None)
            else:
                node["position"]["geographic"] = value
    if editor_config is not None:
        model["pywr_editor"] = editor_config
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model))
    return str(path)


def open_window(qtbot, path, geo_view=True) -> tuple[MainWindow, Schematic]:
    """
    Opens a model with the geographic view enabled or not.
    """
    QTimer.singleShot(100, close_message_box)
    window = MainWindow(path)
    window.editor_settings.save_geo_view(geo_view)
    window.hide()
    if geo_view:
        window.schematic.set_geo_view(False)
        window.schematic.set_geo_view(True)
    return window, window.schematic


def move(window: MainWindow, schematic: Schematic, name: str, dx: float, dy: float):
    """
    Moves a node and pushes the undo command as the schematic does.
    """
    node = schematic.node_items[name]
    node.setPos(node.pos().x() + dx, node.pos().y() + dy)
    window.undo_stack.push(MoveItemCommand(schematic, [node]))


def geographic(window: MainWindow, name: str):
    return window.model_config.nodes.config(name, as_dict=False).geographic_position


class TestGeoViewEditing:
    @pytest.fixture
    def init_window(self, qtbot):
        window, schematic = open_window(qtbot, BASE_MODEL)
        self.initial_json = copy.deepcopy(window.model_config.json)
        yield window, schematic

    def test_nodes_are_movable_and_unlock_keeps_them_movable(self, init_window):
        window, schematic = init_window
        node = schematic.node_items["Reservoir"]
        assert bool(node.flags() & QGraphicsItem.ItemIsMovable) is True

        schematic.toggle_lock()
        assert bool(node.flags() & QGraphicsItem.ItemIsMovable) is False
        schematic.toggle_lock()
        assert bool(node.flags() & QGraphicsItem.ItemIsMovable) is True

    def test_move_writes_geographic_position_only(self, init_window):
        """
        A move in the geographic view is saved as the geographic position, which
        round-trips against an independent pyproj reference, and the schematic
        position is not changed.
        """
        window, schematic = init_window
        node_config = window.model_config.nodes.config("Reservoir", as_dict=False)
        schematic_position = list(node_config.position)

        move(window, schematic, "Reservoir", 40, -25)

        new_scene = schematic.node_items["Reservoir"].pos()
        merc = schematic.geo_transform.scene_to_merc(new_scene.x(), new_scene.y())
        expected = pyproj.Transformer.from_crs(
            "EPSG:3857", "EPSG:4326", always_xy=True
        ).transform(*merc)

        saved = geographic(window, "Reservoir")
        assert saved == pytest.approx(list(expected), abs=1e-5)
        assert saved != [-0.448083, 51.6217]
        assert node_config.position == schematic_position
        assert window.model_config.json != self.initial_json

    def test_undo_redo(self, init_window):
        window, schematic = init_window
        original = geographic(window, "Reservoir")
        move(window, schematic, "Reservoir", 40, 0)
        moved = geographic(window, "Reservoir")
        assert moved != original

        window.undo_stack.undo()
        assert geographic(window, "Reservoir") == original
        window.undo_stack.redo()
        assert geographic(window, "Reservoir") == pytest.approx(moved)

    def test_unlocated_node_is_not_saved_until_moved(self, init_window):
        window, schematic = init_window
        assert geographic(window, "Link2") is None

        # drawing again does not save the default position
        schematic.reload()
        assert geographic(window, "Link2") is None
        assert window.model_config.json == self.initial_json

        move(window, schematic, "Link2", 30, 30)
        assert geographic(window, "Link2") is not None
        assert schematic.geo_view_banner.isHidden() is True

        # undo removes the key again
        window.undo_stack.undo()
        assert geographic(window, "Link2") is None
        assert "geographic" not in window.model_config.nodes.config("Link2")["position"]

    def test_default_positions_do_not_overlap(self, qtbot, tmp_path):
        path = model_with(
            tmp_path, geographic={"Reservoir": None, "Link1": None, "Link2": None}
        )
        window, schematic = open_window(qtbot, path)
        positions = {
            tuple(node.pos().toTuple()) for node in schematic.node_items.values()
        }
        assert len(positions) == 3
        assert "3 nodes have no geographic position" in schematic.geo_view_banner.text()

    def test_drop_outside_the_map_is_rejected(self, init_window):
        window, schematic = init_window
        node = schematic.node_items["Reservoir"]
        before = node.pos().toTuple()
        # a point far beyond the Web Mercator world
        node.setPos(1e12, 1e12)
        window.undo_stack.push(MoveItemCommand(schematic, [node]))
        assert node.pos().toTuple() == before
        assert geographic(window, "Reservoir") == [-0.448083, 51.6217]


class TestEmptyState:
    def test_europe_is_shown_without_located_nodes(self, qtbot, tmp_path):
        path = model_with(
            tmp_path, geographic={"Reservoir": None, "Link1": None, "Link2": None}
        )
        window, schematic = open_window(qtbot, path)
        initial_json = copy.deepcopy(window.model_config.json)
        window.resize(1000, 800)
        window.show()
        schematic.fit_geo_view()

        # the view shows Europe (with the UK) and the tiles are requested
        south_west, north_east = europe_extent_merc()
        visible = schematic.mapToScene(schematic.viewport().rect()).boundingRect()
        centre = schematic.geo_transform.scene_to_merc(
            visible.center().x(), visible.center().y()
        )
        expected = (
            (south_west[0] + north_east[0]) / 2,
            (south_west[1] + north_east[1]) / 2,
        )
        # fitInView centres to within a couple of pixels, which depends on the
        # parity of the viewport size (and so on the width of the toolbar)
        assert centre == pytest.approx(expected, abs=5e3)
        assert schematic.tile_layer.is_active is True
        # nothing is saved
        assert window.model_config.json == initial_json

    def test_one_located_node_switches_to_the_fitted_view(self, qtbot, tmp_path):
        path = model_with(tmp_path, geographic={"Link1": None, "Link2": None})
        window, schematic = open_window(qtbot, path)
        assert len(schematic.located_merc_points()) == 1


class TestInvalidValues:
    @pytest.mark.parametrize(
        "value",
        [
            "a",
            [1],
            [1, 2, 3],
            ["x", "y"],
            [None, None],
            [True, False],
            {"x": 1},
            [math.inf, 1],
            [math.nan, 1],
            [0, 90],
        ],
    )
    def test_invalid_geographic_values(self, qtbot, tmp_path, value):
        """
        A node with an invalid geographic position is treated as if it had none.
        """
        path = model_with(tmp_path, geographic={"Reservoir": value})
        window, schematic = open_window(qtbot, path, geo_view=False)
        schematic.set_geo_view(True)
        assert window.editor_settings.is_geo_view_enabled is True
        assert "no geographic position" in schematic.geo_view_banner.text()
        schematic.set_geo_view(False)
        assert window.editor_settings.is_geo_view_enabled is False

    @pytest.mark.parametrize("crs", ["not a crs", 4326, ["EPSG:4326"], ""])
    def test_invalid_crs(self, qtbot, tmp_path, crs):
        path = model_with(tmp_path, editor_config={"map": {"crs": crs}})
        window, schematic = open_window(qtbot, path, geo_view=False)
        schematic.set_geo_view(True)
        assert window.editor_settings.is_geo_view_enabled is True
        assert "is not valid" in schematic.geo_view_banner.text()
        assert len(schematic.node_items) == 3

    def test_invalid_layer_fields(self, qtbot, tmp_path):
        layer = {
            "id": "abc",
            "path": "missing.geojson",
            "visible": "false",
            "stroke_width": "thick",
            "stroke_color": 5,
            "crs": "nonsense",
        }
        path = model_with(
            tmp_path, editor_config={"map": {"crs": "EPSG:4326", "layers": [layer]}}
        )
        window, schematic = open_window(qtbot, path)
        config = window.model_config.gis_layers.get_all()[0]
        assert config.visible is True
        assert config.stroke_width == config.default_stroke_width
        schematic.refresh_gis_layers()

    def test_failing_draw_keeps_the_schematic_view(self, qtbot, monkeypatch):
        window, schematic = open_window(qtbot, BASE_MODEL, geo_view=False)

        def fail(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(schematic, "geo_default_centre", fail)
        schematic.set_geo_view(True)
        assert window.editor_settings.is_geo_view_enabled is False
        assert window.app_actions.get("toggle-geo-view").isChecked() is False
        assert len(schematic.node_items) == 3

    def test_failing_startup_draw_opens_the_model(self, qtbot, monkeypatch):
        window, schematic = open_window(qtbot, BASE_MODEL, geo_view=True)
        window.editor_settings.save_geo_view(True)
        calls = []
        original = schematic.draw

        def fail_once():
            if not calls:
                calls.append(1)
                raise RuntimeError("boom")
            original()

        monkeypatch.setattr(schematic, "draw", fail_once)
        schematic.draw_safely()
        assert window.editor_settings.is_geo_view_enabled is False


class TestSavingDoesNotAddMapSection:
    def test_map_section_is_not_added(self, qtbot, tmp_path):
        path = model_with(tmp_path)
        window, schematic = open_window(qtbot, path, geo_view=False)
        schematic.set_geo_view(True)
        schematic.set_geo_view(False)
        assert "map" not in window.model_config.editor_config

        schematic.set_basemap_visible(False)
        assert window.model_config.editor_config["map"]["show_basemap"] is False


class TestPlausibility:
    def test_degrees_with_a_projected_crs_are_reported(self, qtbot, tmp_path):
        # lon/lat values read as British National Grid metres
        path = model_with(tmp_path, editor_config={"map": {"crs": "EPSG:27700"}})
        window, schematic = open_window(qtbot, path)
        assert "look like longitudes and latitudes" in schematic.geo_view_banner.text()

    def test_crs_outside_area_of_use_is_reported(self, qtbot, tmp_path):
        # Lambert 93 (France) coordinates of Paris read as British National Grid
        path = model_with(
            tmp_path,
            editor_config={"map": {"crs": "EPSG:27700"}},
            geographic={"Reservoir": [652000, 6862000], "Link1": [700000, 6600000]},
        )
        window, schematic = open_window(qtbot, path)
        text = schematic.geo_view_banner.text()
        assert "2 of 2 nodes are outside the area where EPSG:27700" in text

    def test_valid_coordinates_are_not_reported(self, qtbot):
        window, schematic = open_window(qtbot, BASE_MODEL)
        assert "outside the area" not in schematic.geo_view_banner.text()

    def test_projected_crs_with_right_coordinates(self, qtbot, tmp_path):
        to_bng = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
        path = model_with(
            tmp_path,
            editor_config={"map": {"crs": "EPSG:27700"}},
            geographic={
                "Reservoir": list(to_bng.transform(-0.448083, 51.6217)),
                "Link1": list(to_bng.transform(-1.5, 52.1)),
            },
        )
        window, schematic = open_window(qtbot, path)
        assert "outside the area" not in schematic.geo_view_banner.text()
        # the same place as the lon/lat model
        reference_window, reference = open_window(qtbot, BASE_MODEL)
        for name in ["Reservoir", "Link1"]:
            assert schematic.node_items[name].pos().toTuple() == pytest.approx(
                reference.node_items[name].pos().toTuple(), abs=0.5
            )


class TestNotice:
    def test_notice_is_shown_once(self, qtbot, tmp_path):
        window, schematic = open_window(qtbot, BASE_MODEL, geo_view=False)
        window.editor_settings.save_map_notice_shown(False)
        schematic.show_map_notice(True)
        assert window.editor_settings.is_map_notice_shown is True
        window.statusBar().clearMessage()
        schematic.show_map_notice(True)
        assert window.statusBar().currentMessage() == ""


class TestSetGeoView:
    def test_is_idempotent_and_emits_the_signal(self, qtbot):
        window, schematic = open_window(qtbot, BASE_MODEL, geo_view=False)
        nodes = schematic.node_items
        with qtbot.waitSignal(schematic.geo_view_changed) as blocker:
            schematic.set_geo_view(True)
        assert blocker.args == [True]
        assert window.editor_settings.is_geo_view_enabled is True

        # no change: no signal and the schematic is not drawn again
        drawn = schematic.node_items
        with qtbot.assertNotEmitted(schematic.geo_view_changed):
            schematic.set_geo_view(True)
        assert schematic.node_items is drawn
        assert nodes is not drawn

        with qtbot.waitSignal(schematic.geo_view_changed) as blocker:
            schematic.set_geo_view(False)
        assert blocker.args == [False]

    def test_toolbar_action_follows_the_setting(self, qtbot):
        window, schematic = open_window(qtbot, BASE_MODEL, geo_view=False)
        action = window.app_actions.get("toggle-geo-view")
        assert action.isChecked() is False

        # the action triggers the schematic
        action.trigger()
        assert window.editor_settings.is_geo_view_enabled is True
        assert action.isChecked() is True

        # a change from another control updates the action, without a loop
        schematic.set_geo_view(False)
        assert action.isChecked() is False
        schematic.set_geo_view(True)
        assert action.isChecked() is True

    def test_not_changed_while_the_model_runs(self, qtbot):
        window, schematic = open_window(qtbot, BASE_MODEL, geo_view=False)
        window.is_model_running = True
        action = window.app_actions.get("toggle-geo-view")
        action.setChecked(True)
        schematic.set_geo_view(True)
        assert window.editor_settings.is_geo_view_enabled is False
        assert action.isChecked() is False
        window.is_model_running = False


def test_polygon_footprint(qtbot, tmp_path):
    """
    A node whose geographic position is a GeoJSON polygon is placed at the polygon
    centroid, shows the polygon on the map, and moving it translates the polygon.
    """
    with open(BASE_MODEL) as fp:
        first = json.load(fp)["nodes"][0]
    name = first["name"]
    cx, cy = first["position"]["geographic"]
    ring = [
        [cx - 0.1, cy - 0.1, 0.0],
        [cx + 0.1, cy - 0.1, 0.0],
        [cx + 0.1, cy + 0.1, 0.0],
        [cx - 0.1, cy + 0.1, 0.0],
        [cx - 0.1, cy - 0.1, 0.0],
    ]
    polygon = {"type": "Polygon", "coordinates": [ring]}
    path = model_with(tmp_path, geographic={name: polygon})
    window, schematic = open_window(qtbot, path)

    assert geographic(window, name) == pytest.approx([cx, cy])
    assert name in schematic.node_footprints.items
    assert schematic.node_footprints.items[name].isVisible()

    schematic.set_node_hidden(name, True)
    assert not schematic.node_footprints.items[name].isVisible()
    schematic.set_node_hidden(name, False)

    move(window, schematic, name, 20, 0)
    stored = window.model_config.nodes.config(name, as_dict=False).raw_geographic
    assert isinstance(stored, dict)
    new = geographic(window, name)
    assert new[0] > cx
    assert stored["coordinates"][0][0][0] == pytest.approx(new[0] - 0.1)

    window.undo_stack.undo()
    assert geographic(window, name) == pytest.approx([cx, cy])
    window.editor_settings.instance.clear()


def test_polygon_footprint_is_clickable(qtbot, tmp_path):
    """Clicking the polygon of a node selects the node."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    with open(BASE_MODEL) as fp:
        first = json.load(fp)["nodes"][0]
    name = first["name"]
    cx, cy = first["position"]["geographic"]
    d = 0.3
    ring = [[cx - d, cy - d], [cx + d, cy - d], [cx + d, cy + d], [cx - d, cy + d]]
    path = model_with(
        tmp_path, geographic={name: {"type": "Polygon", "coordinates": [ring]}}
    )
    window, schematic = open_window(qtbot, path)
    window.show()
    footprint = schematic.node_footprints.items[name]
    node = schematic.node_items[name]
    # a point inside the polygon, away from the node symbol
    rect = footprint.sceneBoundingRect()
    point = rect.topLeft() + (rect.bottomRight() - rect.topLeft()) * 0.1
    view_pos = schematic.mapFromScene(point)
    assert footprint in schematic.items(view_pos)
    assert not node.isSelected()
    QTest.mouseClick(schematic.viewport(), Qt.LeftButton, pos=view_pos)
    assert node.isSelected()
    window.editor_settings.instance.clear()


class TestSnapToGrid:
    """
    Snap to grid only applies to the schematic view
    """

    @staticmethod
    def open(qtbot, tmp_path, geo_view: bool):
        QTimer.singleShot(100, close_message_box)
        window = MainWindow(model_with(tmp_path))
        window.editor_settings.save_snap_to_grid(True)
        window.editor_settings.save_grid_size(50)
        window.hide()
        if geo_view:
            window.schematic.set_geo_view(True)
        return window, window.schematic

    def test_nodes_are_not_snapped_in_the_geographic_view(self, qtbot, tmp_path):
        window, schematic = self.open(qtbot, tmp_path, geo_view=True)
        node = schematic.node_items["Reservoir"]

        # drawn where the map puts it, not on a grid point
        position = window.model_config.nodes.config(
            "Reservoir", as_dict=False
        ).geographic_position
        expected = schematic.to_geo_px(position)
        assert node.pos().toTuple() == pytest.approx(tuple(expected))
        assert (expected[0] % 50, expected[1] % 50) != (0, 0)

        node.setPos(123.4, 567.8)
        assert node.pos().toTuple() == pytest.approx((123.4, 567.8))

    def test_nodes_are_snapped_in_the_schematic_view(self, qtbot, tmp_path):
        window, schematic = self.open(qtbot, tmp_path, geo_view=False)
        node = schematic.node_items["Reservoir"]
        node.setPos(123.4, 567.8)
        assert node.pos().toTuple() == pytest.approx((100, 550))

    def test_snapping_comes_back_with_the_schematic_view(self, qtbot, tmp_path):
        window, schematic = self.open(qtbot, tmp_path, geo_view=True)
        schematic.set_geo_view(False)
        node = schematic.node_items["Reservoir"]
        node.setPos(123.4, 567.8)
        assert node.pos().toTuple() == pytest.approx((100, 550))


class TestMissingPositionBanner:
    def test_message_names_the_nodes(self, qtbot, tmp_path):
        path = model_with(tmp_path, geographic={"Link2": None})
        window, schematic = open_window(qtbot, path)

        assert schematic.nodes_without_geo_position() == ["Link2"]
        assert schematic.missing_position_message() == (
            "1 node has no geographic position ('Link2') - drag it into place"
        )
        assert "Link2" in schematic.geo_view_banner.text()
        assert "missing-nodes" in schematic.geo_view_banner.text()

    def test_message_lists_a_few_nodes(self, qtbot, tmp_path):
        path = model_with(
            tmp_path, geographic={"Reservoir": None, "Link1": None, "Link2": None}
        )
        window, schematic = open_window(qtbot, path)
        names = schematic.nodes_without_geo_position()
        assert len(names) == 3
        message = schematic.missing_position_message()
        assert message.startswith("3 nodes have no geographic position (")
        assert all(f"'{name}'" in message for name in names)
        assert message.endswith("- drag them into place")

        schematic.max_listed_nodes = 1
        message = schematic.missing_position_message()
        assert message.count("'") == 2
        assert "and 2 more" in message

    def test_no_message_when_all_nodes_have_a_position(self, qtbot, tmp_path):
        window, schematic = open_window(
            qtbot, model_with(tmp_path, geographic={"Link2": [-1.0, 52.0]})
        )
        assert schematic.nodes_without_geo_position() == []
        assert schematic.missing_position_message() is None

    def test_link_selects_and_centres_the_nodes(self, qtbot, tmp_path):
        path = model_with(tmp_path, geographic={"Link2": None})
        window, schematic = open_window(qtbot, path)
        schematic.scene.clearSelection()

        schematic.on_geo_banner_link("missing-nodes")

        selected = [item.name for item in schematic.scene.selectedItems()]
        assert selected == ["Link2"]
        centre = schematic.mapToScene(schematic.viewport().rect().center())
        node = schematic.node_items["Link2"]
        assert centre.x() == pytest.approx(node.sceneBoundingRect().center().x(), abs=2)
        assert centre.y() == pytest.approx(node.sceneBoundingRect().center().y(), abs=2)
