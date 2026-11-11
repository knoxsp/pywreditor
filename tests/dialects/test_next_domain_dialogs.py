import shutil

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QMessageBox

from pywr_editor import MainWindow
from pywr_editor.dialogs.next_domain.scenarios_dialog import NextScenariosDialog
from pywr_editor.dialogs.next_domain.time_dialog import NextTimeDialog
from pywr_editor.model import ModelConfig
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"
DIALOG_MODULE = "pywr_editor.dialogs.next_domain.scenarios_dialog"


@pytest.fixture(autouse=True)
def yes_to_questions(monkeypatch):
    monkeypatch.setattr(
        f"{DIALOG_MODULE}.QMessageBox.question",
        staticmethod(lambda *args: QMessageBox.StandardButton.Yes),
    )


@pytest.fixture
def model_file(tmp_path):
    file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "time-series.json", file)
    return file


@pytest.fixture
def model(model_file) -> ModelConfig:
    return ModelConfig(str(model_file))


class TestTimeDialog:
    def test_shows_the_time(self, qtbot, model):
        dialog = NextTimeDialog(model)
        qtbot.addWidget(dialog)
        time = model.json["time"]
        assert dialog.start.text() == time["start"]
        assert dialog.end.text() == time["end"]
        assert dialog.kind.currentData() == time["timestep"]["type"]
        assert not dialog.save_button.isEnabled()
        assert "timesteps of" in dialog.summary.text()
        assert dialog.problems.text() == ""

    def test_change_dates_and_timestep(self, qtbot, model):
        dialog = NextTimeDialog(model)
        qtbot.addWidget(dialog)
        dialog.start.date.setDate(QDate(2020, 3, 1))
        dialog.end.date.setDate(QDate(2020, 3, 31))
        dialog.number.setValue(5)
        assert dialog.save_button.isEnabled()
        assert "7 timesteps of 5 days" in dialog.summary.text()
        assert dialog.save()
        assert model.json["time"] == {
            **model.json["time"],
            "start": "2020-03-01",
            "end": "2020-03-31",
            "timestep": {"type": "Days", "days": 5},
        }
        assert not dialog.save_button.isEnabled()

    def test_hours_with_a_time_of_day(self, qtbot, model):
        dialog = NextTimeDialog(model)
        qtbot.addWidget(dialog)
        dialog.start.use_time.setChecked(True)
        dialog.end.use_time.setChecked(True)
        dialog.end.date.setDate(dialog.start.date.date().addDays(1))
        index = dialog.kind.findData("Hours")
        dialog.kind.setCurrentIndex(index)
        dialog.number.setValue(6)
        assert dialog.number.suffix() == " hours"
        assert dialog.save()
        time = model.json["time"]
        assert time["start"].endswith("T00:00:00") and time["end"].endswith("T00:00:00")
        assert time["timestep"] == {"type": "Hours", "hours": 6}
        assert "5 timesteps of 6 hours" in dialog.summary.text()

    def test_frequency(self, qtbot, model):
        dialog = NextTimeDialog(model)
        qtbot.addWidget(dialog)
        dialog.kind.setCurrentIndex(dialog.kind.findData("Frequency"))
        assert dialog.frequency.isVisibleTo(dialog)
        assert not dialog.number.isVisibleTo(dialog)
        dialog.frequency.setText("often")
        assert "not recognised" in dialog.problems.text()
        assert not dialog.save()
        dialog.frequency.setText("1 month")
        assert dialog.problems.text() == ""
        assert dialog.save()
        assert model.json["time"]["timestep"] == {"type": "Frequency", "freq": "1 month"}

    def test_end_before_start_is_not_saved(self, qtbot, model):
        dialog = NextTimeDialog(model)
        qtbot.addWidget(dialog)
        before = dict(model.json["time"])
        dialog.end.date.setDate(QDate(1990, 1, 1))
        assert "before the start" in dialog.problems.text()
        assert not dialog.save()
        assert model.json["time"] == before

    def test_other_keys_are_kept(self, qtbot, model):
        model.json["time"]["custom"] = {"x": 1}
        dialog = NextTimeDialog(model)
        qtbot.addWidget(dialog)
        dialog.number.setValue(2)
        assert dialog.save()
        assert model.json["time"]["custom"] == {"x": 1}


class TestScenariosDialog:
    def make(self, qtbot, model, selected=None):
        dialog = NextScenariosDialog(model, selected)
        qtbot.addWidget(dialog)
        return dialog

    def test_empty_model(self, qtbot, model):
        dialog = self.make(qtbot, model)
        assert dialog.list.count() == 0
        assert dialog.summary.text() == "No scenarios: the model runs once"
        assert not dialog.name.isEnabled()

    def test_add_group_and_save(self, qtbot, model):
        dialog = self.make(qtbot, model)
        dialog.on_add()
        dialog.name.setText("Climate")
        dialog.size.setValue(3)
        dialog.labels.setPlainText("dry\nmedian\nwet")
        assert dialog.summary.text() == "3 scenarios simulated"
        assert dialog.save()
        assert model.json["scenarios"] == {
            "groups": [{"name": "Climate", "size": 3, "labels": ["dry", "median", "wet"]}]
        }
        assert not dialog.save_button.isEnabled()

        dialog = self.make(qtbot, model, "Climate")
        assert dialog.name.text() == "Climate"
        assert dialog.size.value() == 3
        assert dialog.labels.toPlainText() == "dry\nmedian\nwet"

    def test_subsets(self, qtbot, model):
        model.json["scenarios"] = {"groups": [{"name": "A", "size": 5}, {"name": "B", "size": 2}]}
        dialog = self.make(qtbot, model, "A")
        dialog.subset_type.setCurrentIndex(dialog.subset_type.findData("Slice"))
        dialog.slice_start.setValue(1)
        dialog.slice_end.setValue(4)
        assert dialog.summary.text() == "6 scenarios simulated"
        dialog.subset_type.setCurrentIndex(dialog.subset_type.findData("Indices"))
        dialog.indices.setText("0, 4")
        assert dialog.summary.text() == "4 scenarios simulated"
        dialog.indices.setText("0, 9")
        assert "indices of" in dialog.problems.text()
        assert not dialog.save()
        dialog.subset_type.setCurrentIndex(dialog.subset_type.findData("Labels"))
        dialog.labels.setPlainText("a\nb\nc\nd\ne")
        dialog.subset_labels.setPlainText("b\nd")
        assert dialog.summary.text() == "4 scenarios simulated"
        assert dialog.save()
        group = model.json["scenarios"]["groups"][0]
        assert group["subset"] == {"type": "Labels", "labels": ["b", "d"]}
        # removing the subset
        dialog.subset_type.setCurrentIndex(0)
        assert dialog.save()
        assert "subset" not in model.json["scenarios"]["groups"][0]

    def test_validation_blocks_saving(self, qtbot, model):
        dialog = self.make(qtbot, model)
        dialog.on_add()
        dialog.on_add()
        dialog.name.setText(dialog.groups[0]["name"])
        assert "used twice" in dialog.problems.text()
        assert not dialog.save()
        assert "scenarios" not in model.json

    def test_rename_updates_references(self, qtbot, model):
        model.json["scenarios"] = {"groups": [{"name": "Climate", "size": 2}]}
        model.json["network"]["parameters"].append(
            {
                "type": "ConstantScenario",
                "meta": {"name": "by_climate"},
                "scenario_group": "Climate",
                "values": [1.0, 2.0],
            }
        )
        dialog = self.make(qtbot, model, "Climate")
        dialog.name.setText("Rain")
        assert dialog.save()
        assert model.json["scenarios"]["groups"][0]["name"] == "Rain"
        parameter = [
            p for p in model.json["network"]["parameters"] if p["meta"]["name"] == "by_climate"
        ][0]
        assert parameter["scenario_group"] == "Rain"
        # a second rename uses the new name
        dialog.name.setText("Weather")
        assert dialog.save()
        assert parameter["scenario_group"] == "Weather"

    def test_delete_last_group_removes_scenarios(self, qtbot, model):
        model.json["scenarios"] = {"groups": [{"name": "A", "size": 2}]}
        dialog = self.make(qtbot, model, "A")
        dialog.on_delete()
        assert dialog.list.count() == 0
        assert dialog.save()
        assert "scenarios" not in model.json

    def test_move_and_combinations_follow(self, qtbot, model):
        model.json["scenarios"] = {
            "groups": [
                {"name": "A", "size": 2, "labels": ["x", "y"]},
                {"name": "B", "size": 3},
            ],
            "combinations": [["x", 2], ["y", 0]],
        }
        dialog = self.make(qtbot, model, "A")
        assert dialog.use_combinations.isChecked()
        assert dialog.combinations.rowCount() == 2
        assert dialog.summary.text() == "2 scenarios simulated"
        dialog.on_move(1)
        assert [g["name"] for g in dialog.groups] == ["B", "A"]
        assert dialog.domain["combinations"] == [[2, "x"], [0, "y"]]
        assert dialog.save()
        assert model.json["scenarios"]["combinations"] == [[2, "x"], [0, "y"]]

    def test_edit_combinations(self, qtbot, model):
        model.json["scenarios"] = {
            "groups": [{"name": "A", "size": 2}, {"name": "B", "size": 2}]
        }
        dialog = self.make(qtbot, model, "A")
        assert not dialog.use_combinations.isChecked()
        dialog.use_combinations.setChecked(True)
        # all the combinations by default
        assert dialog.combinations.rowCount() == 4
        dialog.combinations.setCurrentCell(0, 0)
        dialog.on_remove_combination()
        assert dialog.summary.text() == "3 scenarios simulated"
        dialog.combinations.item(0, 1).setText("9")
        assert "outside the 2 scenarios" in dialog.problems.text()
        dialog.combinations.item(0, 1).setText("1")
        assert dialog.save()
        assert model.json["scenarios"]["combinations"] == [[0, 1], [1, 0], [1, 1]]
        dialog.use_combinations.setChecked(False)
        assert dialog.save()
        assert "combinations" not in model.json["scenarios"]

    def test_unknown_keys_are_kept(self, qtbot, model):
        model.json["scenarios"] = {
            "groups": [{"name": "A", "size": 2, "extra": 1}],
            "other": True,
        }
        dialog = self.make(qtbot, model, "A")
        dialog.size.setValue(3)
        assert dialog.save()
        assert model.json["scenarios"] == {
            "groups": [{"name": "A", "size": 3, "extra": 1}],
            "other": True,
        }

    def test_closing_with_changes_asks(self, qtbot, model, monkeypatch):
        dialog = self.make(qtbot, model)
        dialog.on_add()
        asked = []
        monkeypatch.setattr(
            f"{DIALOG_MODULE}.QMessageBox.question",
            staticmethod(lambda *args: asked.append(args) or QMessageBox.StandardButton.No),
        )
        dialog.close()
        assert asked
        assert "scenarios" not in model.json


def test_window_has_the_buttons_and_updates_the_toolbar(qtbot, model_file):
    window = MainWindow(str(model_file))
    window.hide()
    assert window.app_actions.get("edit-time") is not None
    assert window.app_actions.get("edit-scenario-domain") is not None
    assert window.time_stepper.editable
    window.app_actions.get("edit-time").trigger()
    dialogs = [d for d in window.findChildren(NextTimeDialog)]
    assert len(dialogs) == 1
    dialog = dialogs[0]
    dialog.kind.setCurrentIndex(dialog.kind.findData("Hours"))
    dialog.number.setValue(6)
    assert dialog.save()
    # the toolbar cannot edit hours: it is disabled
    assert not window.time_stepper.editable
    assert not window.time_stepper.time_step.isEnabled()
    assert not window.time_stepper.start_date.isEnabled()
    dialog.kind.setCurrentIndex(dialog.kind.findData("Days"))
    dialog.number.setValue(2)
    assert dialog.save()
    assert window.time_stepper.editable
    assert window.time_stepper.time_step.value() == 2
    assert window.time_stepper.time_step.isEnabled()
    dialog.close()

    window.app_actions.get("edit-scenario-domain").trigger()
    assert len(window.findChildren(NextScenariosDialog)) == 1
    window.model_config.reset_change_flag()
    for dialog in window.findChildren(NextScenariosDialog):
        dialog.save_button.setEnabled(False)
        dialog.close()
    window.close()


def test_toolbar_keeps_a_time_of_day(qtbot, model_file):
    model = ModelConfig(str(model_file))
    model.json["time"]["start"] = "2015-01-01T06:00:00"
    model.json["time"]["end"] = "2015-01-05T06:00:00"
    model.json["time"]["timestep"] = {"type": "Hours", "hours": 6}
    window = MainWindow(str(model_file))
    window.hide()
    window.model_config.json["time"] = model.json["time"]
    window.time_stepper.refresh()
    assert not window.time_stepper.editable
    assert window.time_stepper.start_date.date() == QDate(2015, 1, 1)
    assert window.model_config.json["time"]["start"] == "2015-01-01T06:00:00"
    window.model_config.reset_change_flag()
    window.close()
