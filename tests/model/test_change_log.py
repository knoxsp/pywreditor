import pytest

from pywr_editor.model import ModelConfig
from pywr_editor.model.change_log import (
    ADDED,
    CHANGED,
    REMOVED,
    REORDERED,
    ChangeLog,
    diff,
    format_path,
)
from tests.utils import resolve_model_path


def kinds(old, new) -> list[tuple[str, str]]:
    return [(c.kind, c.path_text) for c in diff(old, new)]


class TestDiff:
    def test_no_difference(self):
        assert kinds({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2}]}) == []

    def test_dictionary(self):
        old = {"keep": 1, "gone": 2, "edit": {"x": 1}}
        new = {"keep": 1, "new": 3, "edit": {"x": 2}}
        assert sorted(kinds(old, new)) == [
            (ADDED, "new"),
            (CHANGED, "edit.x"),
            (REMOVED, "gone"),
        ]

    def test_type_change_is_a_change(self):
        # 1 == True in Python
        assert kinds({"a": 1}, {"a": True}) == [(CHANGED, "a")]
        assert kinds({"a": 1}, {"a": 1.0}) == [(CHANGED, "a")]

    def test_named_items_are_matched_by_name(self):
        old = {"nodes": [{"name": "A", "v": 1}, {"name": "B", "v": 1}]}
        # a node is inserted before the others: nothing else must change
        new = {
            "nodes": [
                {"name": "C", "v": 1},
                {"name": "A", "v": 1},
                {"name": "B", "v": 2},
            ]
        }
        result = kinds(old, new)
        assert (ADDED, 'nodes["C"]') in result
        assert (CHANGED, 'nodes["B"].v') in result
        assert (REORDERED, "nodes") not in result  # C is new; A, B keep their order
        assert len(result) == 2

    def test_reordered_named_items(self):
        old = [{"name": "A"}, {"name": "B"}]
        new = [{"name": "B"}, {"name": "A"}]
        assert kinds({"n": old}, {"n": new}) == [(REORDERED, "n")]

    def test_unnamed_items_added_and_removed(self):
        old = {"edges": [["A", "B"], ["B", "C"]]}
        new = {"edges": [["B", "C"], ["C", "D"], ["D", "E"]]}
        changes = list(diff(old, new))
        assert [(c.kind, c.old, c.new) for c in changes if c.kind == REMOVED][0][1] == [
            "A",
            "B",
        ]
        added = [c.new for c in changes if c.kind == ADDED]
        assert added == [["C", "D"], ["D", "E"]]
        assert len(changes) == 3

    def test_unnamed_items_same_length(self):
        assert kinds({"a": [1, 2, 3]}, {"a": [1, 5, 3]}) == [(CHANGED, "a[1]")]

    def test_duplicate_names_fall_back_to_position(self):
        old = [{"name": "A", "v": 1}, {"name": "A", "v": 1}]
        new = [{"name": "A", "v": 1}, {"name": "A", "v": 2}]
        assert kinds({"n": old}, {"n": new}) == [(CHANGED, "n[1].v")]

    def test_format_path(self):
        assert format_path(()) == "model"


class TestChangeLog:
    def test_record(self):
        model = {"a": 1}
        log = ChangeLog()
        assert log.record(model) is None  # not started
        log.start(model)
        assert log.record(model) is None  # nothing changed
        model["a"] = 2
        change_set = log.record(model, "Edit a")
        assert change_set.number == 1
        assert change_set.summary == "Edit a"
        assert change_set.changes[0].old == 1 and change_set.changes[0].new == 2
        assert log.record(model) is None  # already logged

    def test_snapshot_is_a_copy(self):
        model = {"a": {"b": [1]}}
        log = ChangeLog()
        log.start(model)
        model["a"]["b"].append(2)  # nested change must not alter the snapshot
        assert len(log.record(model).changes) == 1

    def test_saved_marker(self):
        model = {"a": 1}
        log = ChangeLog()
        log.start(model)
        model["a"] = 2
        first = log.record(model)
        log.mark_saved()
        model["a"] = 3
        second = log.record(model)
        assert log.is_saved(first) and not log.is_saved(second)
        assert log.unsaved == [second]

    def test_limit(self, monkeypatch):
        monkeypatch.setattr("pywr_editor.model.change_log.MAX_CHANGE_SETS", 3)
        model = {"a": 0}
        log = ChangeLog()
        log.start(model)
        for i in range(1, 6):
            model["a"] = i
            log.record(model)
        assert [c.number for c in log.change_sets] == [3, 4, 5]

    def test_to_list_is_json(self):
        import json

        model = {"a": 1}
        log = ChangeLog()
        log.start(model)
        model["a"] = 2
        log.record(model)
        assert json.loads(json.dumps(log.to_list()))[0]["changes"] == [
            {"kind": CHANGED, "path": "a", "old": 1, "new": 2}
        ]


class TestModelConfigLog:
    @pytest.fixture
    def model(self) -> ModelConfig:
        return ModelConfig(resolve_model_path("model_1.json"))

    def test_opening_is_not_logged(self, model):
        assert len(model.change_log) == 0
        assert model.last_change is None

    def test_edits_are_logged(self, model):
        model.start_date = "2001-01-01"
        last = model.last_change
        assert len(model.change_log) == 1
        assert [(c.kind, c.path_text) for c in last.changes] == [
            (CHANGED, "timestepper.start")
        ]

        node = model.json["nodes"][0]["name"]
        model.nodes.set_position(node_name=node, position=[10, 20])
        assert model.last_change.changes[0].path_text.startswith(f'nodes["{node}"]')
        assert len(model.change_log) == 2

    def test_delete_edge_logs_the_deleted_edge(self, model):
        edge = model.json["edges"][0]
        model.edges.delete(source_node_name=edge[0], target_node_name=edge[1])
        changes = model.last_change.changes
        assert any(c.kind == REMOVED and c.old == edge for c in changes)

    def test_label(self, model):
        model.json["metadata"]["title"] = "Another"
        model.has_changed(label="Renamed the model")
        assert model.last_change.summary == "Renamed the model"

    def test_save_marks_changes_as_saved(self, model, tmp_path):
        import shutil

        file = tmp_path / "model.json"
        shutil.copy(resolve_model_path("model_1.json"), file)
        model = ModelConfig(str(file))
        model.start_date = "2002-02-02"
        assert len(model.change_log.unsaved) == 1
        assert model.save() is True
        assert model.change_log.unsaved == []
        assert len(model.change_log) == 1


class TestNetChanges:
    def test_net_changes_since_opened_and_saved(self):
        log = ChangeLog()
        model = {"a": 1, "b": {"c": 2}}
        log.start(model)
        assert log.net_changes(model) == []

        model["a"] = 2
        log.record(model)
        model["a"] = 3
        log.record(model)
        # edits to the same value are one change
        assert [c.path for c in log.net_changes(model)] == [("a",)]
        assert log.net_changes(model)[0].new == 3

        # an edit that was undone is not a change
        model["a"] = 1
        log.record(model)
        assert log.net_changes(model) == []

        model["b"]["c"] = 5
        log.record(model)
        log.mark_saved(model)
        assert log.net_changes(model, since_saved=True) == []
        assert len(log.net_changes(model)) == 1

    def test_not_tracking(self):
        assert ChangeLog().net_changes({"a": 1}) == []
