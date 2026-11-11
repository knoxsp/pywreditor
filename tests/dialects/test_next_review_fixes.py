import json

import pytest
from PySide6.QtCore import QDate

from pywr_editor import MainWindow
from pywr_editor.model.connection_rules import Endpoint, Role, check_connection
from pywr_editor.model.edges import EdgeRecord
from pywr_editor.schematic.commands.delete_item_command import DeleteItemCommand
from pywr_editor.schematic.commands.disconnect_node_command import (
    DisconnectNodeCommand,
)

"""
 Regression tests for the problems found by the review of the pull request: an edge
 lost its meta when a deletion was undone, edges that use different slots were
 duplicates, and models with a time of day could not be run.
"""

META = {"comment": "feeds the link", "tags": {"a": "b"}}


@pytest.fixture(autouse=True)
def no_error_dialog(monkeypatch):
    """
    A run that is refused shows a modal message: a test that fails must not wait for it.
    """
    shown = []
    monkeypatch.setattr(
        MainWindow, "on_error_message", lambda self, text, *a, **k: shown.append(text)
    )
    return shown


def next_model(start="2020-01-01", end="2020-01-10", timestep=None, edges=None) -> dict:
    nodes = (("in", "Input", [100, 100]), ("link", "Link", [250, 100]), ("out", "Output", [400, 100]))
    return {
        "metadata": {"title": "t"},
        "time": {
            "start": start,
            "end": end,
            "timestep": timestep or {"type": "Days", "days": 1},
        },
        "network": {
            "nodes": [
                {"meta": {"name": n, "position": {"schematic": p}}, "type": t}
                for n, t, p in nodes
            ],
            "edges": edges
            if edges is not None
            else [
                {"from_node": "in", "to_node": "link", "meta": META},
                {"from_node": "link", "to_node": "out"},
            ],
        },
    }


def open_window(qtbot, tmp_path, model: dict) -> MainWindow:
    file = tmp_path / "model.json"
    file.write_text(json.dumps(model))
    window = MainWindow(str(file))
    window.hide()
    return window


@pytest.fixture
def window(qtbot, tmp_path):
    window = open_window(qtbot, tmp_path, next_model())
    yield window
    window.model_config.reset_change_flag()
    window.close()


def edge_between(window, source: str, target: str) -> dict:
    return next(
        e
        for e in window.model_config.json["network"]["edges"]
        if e["from_node"] == source and e["to_node"] == target
    )


class TestEdgeMeta:
    def test_the_record_keeps_the_meta_but_is_identified_without_it(self, window):
        record = window.model_config.edges.find_record("in", "link")
        assert record.extra == {"meta": META}
        assert record == EdgeRecord("in", "link")
        assert window.model_config.edges.find_record("link", "out").extra is None

    def test_deleting_a_node_and_undoing_restores_the_meta(self, window):
        schematic = window.schematic
        command = DeleteItemCommand(schematic, [schematic.node_items["link"]])
        command.redo()
        assert window.model_config.edges.count == 0
        command.undo()
        assert window.model_config.edges.count == 2
        assert edge_between(window, "in", "link")["meta"] == META
        assert "meta" not in edge_between(window, "link", "out")

    def test_disconnecting_and_undoing_restores_the_meta(self, window):
        command = DisconnectNodeCommand(window.schematic, "in", "link")
        command.redo()
        assert window.model_config.edges.find_record("in", "link") is None
        command.undo()
        assert edge_between(window, "in", "link")["meta"] == META

    def test_the_restored_meta_is_a_copy(self, window):
        record = window.model_config.edges.find_record("in", "link")
        record.extra["meta"]["comment"] = "changed"
        assert edge_between(window, "in", "link")["meta"]["comment"] == "feeds the link"

    def test_redoing_after_the_undo_keeps_working(self, window):
        command = DeleteItemCommand(window.schematic, [window.schematic.node_items["link"]])
        for _ in range(2):
            command.redo()
            command.undo()
        assert edge_between(window, "in", "link")["meta"] == META


class TestSlotsInDuplicates:
    A = Endpoint("a", Role.THROUGH, label="Link")
    B = Endpoint("b", Role.THROUGH, label="Link")

    def test_edges_that_use_different_slots_are_different_connections(self):
        existing = [EdgeRecord("a", "b", "slot1", None)]
        assert check_connection(self.A, self.B, existing, "slot2", None) is None
        assert check_connection(self.A, self.B, existing, None, None) is None
        assert check_connection(self.A, self.B, existing, "slot1", "other") is None

    def test_the_same_slots_are_a_duplicate(self):
        existing = [EdgeRecord("a", "b", "slot1", "slot2")]
        issue = check_connection(self.A, self.B, existing, "slot1", "slot2")
        assert issue is not None and issue.kind == "duplicate"
        assert check_connection(self.A, self.B, [EdgeRecord("a", "b")]).kind == "duplicate"

    def test_the_validation_of_a_model_uses_the_slots(self):
        from pywr_editor.dialects.next.validation import validate_network

        model = next_model(
            edges=[
                {"from_node": "in", "to_node": "link"},
                {"from_node": "link", "to_node": "out", "from_slot": {"type": "River"}},
                {"from_node": "link", "to_node": "out", "from_slot": {"type": "Spill"}},
                {"from_node": "link", "to_node": "out", "from_slot": {"type": "Spill"}},
            ]
        )
        duplicates = [
            d for d in validate_network(model) if "already connected" in d.message
        ]
        # only the second Spill edge repeats an edge
        assert [d.path for d in duplicates] == [("network", "edges", 3)]


HOURLY = {"type": "Hours", "hours": 1}


class TestRunWithTimeOfDay:
    def test_a_model_of_hours_in_one_day_can_run(self, qtbot, tmp_path):
        """
        The toolbar shows the dates, which are the same for a model that runs from 06:00
        to 18:00: the model itself must be checked.
        """
        window = open_window(
            qtbot, tmp_path, next_model("2020-01-01T06:00:00", "2020-01-01T18:00:00", HOURLY)
        )
        try:
            bar = window.time_stepper
            assert bar.start_date.date() == bar.end_date.date()
            assert window.run_widget.validate_timestepper() is True
        finally:
            window.model_config.reset_change_flag()
            window.close()

    def test_the_start_must_still_be_before_the_end(self, qtbot, tmp_path, monkeypatch):
        window = open_window(
            qtbot, tmp_path, next_model("2020-01-01T18:00:00", "2020-01-01T06:00:00", HOURLY)
        )
        messages = []
        monkeypatch.setattr(window, "on_error_message", lambda text, *a: messages.append(text))
        try:
            assert window.run_widget.validate_timestepper() is False
            assert "must be earlier than the end" in messages[0]
            assert "01/01/2020 18:00" in messages[0]
        finally:
            window.model_config.reset_change_flag()
            window.close()

    def test_run_to_must_be_a_day_of_the_run(self, qtbot, tmp_path, monkeypatch):
        window = open_window(
            qtbot, tmp_path, next_model("2020-01-01T06:00:00", "2020-01-03T18:00:00", HOURLY)
        )
        messages = []
        monkeypatch.setattr(window, "on_error_message", lambda text, *a: messages.append(text))
        try:
            run_to = window.time_stepper.run_to_date
            for day in ((2020, 1, 1), (2020, 1, 2), (2020, 1, 3)):
                run_to.setDate(QDate(*day))
                assert window.run_widget.validate_timestepper() is True, day
            run_to.setDate(QDate(2020, 1, 4))
            assert window.run_widget.validate_timestepper() is False
            assert "must be between the start" in messages[-1]
        finally:
            window.model_config.reset_change_flag()
            window.close()

    def test_run_to_starts_at_the_end_date_of_a_model_with_a_time_of_day(self, qtbot, tmp_path):
        """
        The end date with a time cannot be read as a date: Run-to was 1 January 2000,
        which made every run fail.
        """
        window = open_window(
            qtbot, tmp_path, next_model("2020-01-01", "2020-01-10T00:00:00")
        )
        try:
            bar = window.time_stepper
            assert bar.run_to_date.date().toString("yyyy-MM-dd") == "2020-01-10"
            assert window.run_widget.validate_timestepper() is True
        finally:
            window.model_config.reset_change_flag()
            window.close()

    def test_run_to_follows_the_end_unless_a_date_was_saved(self, qtbot, tmp_path):
        window = open_window(qtbot, tmp_path, next_model("2020-01-01", "2020-01-10T00:00:00"))
        try:
            bar = window.time_stepper
            window.model_config.json["time"]["end"] = "2020-02-01T06:00:00"
            bar.refresh()
            assert bar.run_to_date.date().toString("yyyy-MM-dd") == "2020-02-01"
            # a date the user chose is kept
            window.editor_settings.save_run_to_date("2020-01-15")
            window.model_config.json["time"]["end"] = "2020-03-01T06:00:00"
            bar.refresh()
            assert bar.run_to_date.date().toString("yyyy-MM-dd") == "2020-02-01"
        finally:
            window.model_config.reset_change_flag()
            window.close()

    def test_the_checks_of_the_v1_toolbar_are_unchanged(self, qtbot, tmp_path, monkeypatch):
        model = {
            "metadata": {"title": "t", "minimum_version": "1.19.0"},
            "timestepper": {"start": "2020-01-10", "end": "2020-01-10", "timestep": 1},
            "nodes": [{"name": "n", "type": "Input", "position": {"schematic": [1, 1]}}],
            "edges": [],
        }
        window = open_window(qtbot, tmp_path, model)
        messages = []
        monkeypatch.setattr(window, "on_error_message", lambda text, *a: messages.append(text))
        try:
            assert window.run_widget.validate_timestepper() is False
            assert "must be smaller than the end date" in messages[0]
        finally:
            window.model_config.reset_change_flag()
            window.close()


from pywr_editor.schematic import Edge  # noqa: E402


def edge_items(window, source: str, target: str) -> list:
    return [
        item
        for item in window.schematic.scene.items()
        if isinstance(item, Edge)
        and item.source.name == source
        and item.target.name == target
    ]


class TestEdgesThatUseDifferentSlots:
    """
    Two edges between the same nodes are different connections when they use different
    slots. The schematic draws one edge, and deleting it deletes both, so that an undo
    must restore both (the second one was lost).
    """

    SPILL_META = {"comment": "spill"}

    @pytest.fixture
    def parallel(self, qtbot, tmp_path):
        model = next_model(
            edges=[
                {"from_node": "in", "to_node": "link"},
                {"from_node": "link", "to_node": "out", "from_slot": {"type": "River"}},
                {
                    "from_node": "link",
                    "to_node": "out",
                    "from_slot": {"type": "Spill"},
                    "meta": self.SPILL_META,
                },
            ]
        )
        window = open_window(qtbot, tmp_path, model)
        yield window
        window.model_config.reset_change_flag()
        window.close()

    @staticmethod
    def between(window) -> list[dict]:
        return [
            e
            for e in window.model_config.json["network"]["edges"]
            if (e["from_node"], e["to_node"]) == ("link", "out")
        ]

    def test_one_edge_is_drawn_for_the_two_connections(self, parallel):
        assert len(self.between(parallel)) == 2
        assert len(edge_items(parallel, "link", "out")) == 1

    def test_all_the_records_between_the_nodes_are_found(self, parallel):
        records = parallel.model_config.edges.find_records("link", "out")
        assert [r.source_slot for r in records] == [{"type": "River"}, {"type": "Spill"}]
        assert records[1].extra == {"meta": self.SPILL_META}
        assert parallel.model_config.edges.find_records("out", "link") == []

    def test_disconnecting_and_undoing_restores_both_edges(self, parallel):
        command = DisconnectNodeCommand(parallel.schematic, "link", "out")
        command.redo()
        assert self.between(parallel) == []
        assert edge_items(parallel, "link", "out") == []
        command.undo()
        edges = self.between(parallel)
        assert [e["from_slot"] for e in edges] == [{"type": "River"}, {"type": "Spill"}]
        assert edges[1]["meta"] == self.SPILL_META
        assert len(edge_items(parallel, "link", "out")) == 1

    def test_deleting_a_node_and_undoing_restores_both_edges(self, parallel):
        schematic = parallel.schematic
        command = DeleteItemCommand(schematic, [schematic.node_items["out"]])
        command.redo()
        assert None not in command.deleted_edges
        assert len(command.deleted_edges) == 2
        assert parallel.model_config.edges.count == 1
        command.undo()
        assert len(self.between(parallel)) == 2
        assert self.between(parallel)[1]["meta"] == self.SPILL_META
        assert parallel.model_config.edges.count == 3

    def test_pywr_v1_edges_with_slots(self, qtbot, tmp_path):
        model = {
            "metadata": {"title": "t", "minimum_version": "1.19.0"},
            "timestepper": {"start": "2020-01-01", "end": "2020-01-10", "timestep": 1},
            "nodes": [
                {"name": n, "type": t, "position": {"schematic": p}}
                for n, t, p in (("a", "Link", [100, 100]), ("b", "Link", [300, 100]))
            ],
            "edges": [["a", "b", 1, 1], ["a", "b", 2, 1]],
        }
        window = open_window(qtbot, tmp_path, model)
        try:
            assert len(edge_items(window, "a", "b")) == 1
            command = DisconnectNodeCommand(window.schematic, "a", "b")
            command.redo()
            assert window.model_config.edges.count == 0
            command.undo()
            assert window.model_config.json["edges"] == [["a", "b", 1, 1], ["a", "b", 2, 1]]
        finally:
            window.model_config.reset_change_flag()
            window.close()
