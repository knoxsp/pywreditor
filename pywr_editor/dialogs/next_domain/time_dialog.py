import copy
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, QTime, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.dialects.next import time_domain as td
from pywr_editor.widgets import PushIconButton

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig

"""
 The dialog to edit the time domain of a pywr-next model: the first and last date, with
 an optional time of day, and the timestep in days, hours or as a frequency.
"""


class DateTimeField(QWidget):
    """A date, with an optional time of day."""

    def __init__(self, name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.date = QDateEdit()
        self.date.setObjectName(f"{name}_date")
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.use_time = QCheckBox("Time of day")
        self.use_time.setObjectName(f"{name}_use_time")
        self.time = QTimeEdit()
        self.time.setObjectName(f"{name}_time")
        self.time.setDisplayFormat("HH:mm:ss")
        self.time.setEnabled(False)
        # noinspection PyUnresolvedReferences
        self.use_time.toggled.connect(self.time.setEnabled)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.date)
        layout.addWidget(self.use_time)
        layout.addWidget(self.time)
        layout.addStretch()

    def set_text(self, text: str | None) -> None:
        """
        Shows a date.
        :param text: The date as "2015-01-31" or "2015-01-31T06:00:00".
        :return: None
        """
        value = td.parse_time(text)
        if value is None:
            value = datetime(2000, 1, 1)
            text = None
        self.date.setDate(QDate(value.year, value.month, value.day))
        has_time = td.has_time_of_day(text)
        self.use_time.setChecked(has_time)
        self.time.setTime(QTime(value.hour, value.minute, value.second))

    def text(self) -> str:
        """
        Returns the date as written in the model.
        :return: "2015-01-31", or "2015-01-31T06:00:00" if there is a time of day.
        """
        text = self.date.date().toString("yyyy-MM-dd")
        if self.use_time.isChecked():
            text += "T" + self.time.time().toString("HH:mm:ss")
        return text


class NextTimeDialog(QDialog):
    def __init__(
        self,
        model: "ModelConfig",
        selected_name: str | None = None,
        parent: QWidget | None = None,
    ):
        """
        Initialises the dialog.
        :param model: The model configuration.
        :param selected_name: Not used.
        :param parent: The parent widget. Optional.
        """
        super().__init__(parent)
        self.app = parent
        self.model = model
        self.setWindowTitle("Time")

        self.start = DateTimeField("start")
        self.end = DateTimeField("end")
        self.kind = QComboBox()
        self.kind.setObjectName("timestep_type")
        for name, label in (("Days", "Days"), ("Hours", "Hours"), ("Frequency", "Other (frequency)")):
            self.kind.addItem(label, name)
        self.number = QSpinBox()
        self.number.setObjectName("timestep_number")
        self.number.setRange(1, 100000)
        self.frequency = QLineEdit()
        self.frequency.setObjectName("timestep_frequency")
        self.frequency.setPlaceholderText("7d, 1 month, P7D…")
        timestep = QHBoxLayout()
        timestep.addWidget(self.kind)
        timestep.addWidget(self.number)
        timestep.addWidget(self.frequency, 1)
        timestep_widget = QWidget()
        timestep_widget.setLayout(timestep)
        timestep.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        form.addRow("Start", self.start)
        form.addRow("End (included)", self.end)
        form.addRow("Timestep", timestep_widget)

        self.summary = QLabel()
        self.summary.setObjectName("time_summary")
        self.summary.setWordWrap(True)
        self.problems = QLabel()
        self.problems.setObjectName("time_problems")
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color: #d13438")

        self.save_button = PushIconButton(icon="msc.save", label="Save", accent=True)
        self.save_button.setObjectName("save_button")
        self.save_button.setEnabled(False)
        close_button = PushIconButton(icon="msc.close", label="Close")
        # noinspection PyUnresolvedReferences
        self.save_button.clicked.connect(self.save)
        # noinspection PyUnresolvedReferences
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.save_button)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.summary)
        layout.addWidget(self.problems)
        layout.addStretch()
        layout.addLayout(buttons)

        self.load()
        for signal in (
            self.start.date.dateChanged,
            self.end.date.dateChanged,
            self.start.use_time.toggled,
            self.end.use_time.toggled,
            self.start.time.timeChanged,
            self.end.time.timeChanged,
            self.kind.currentIndexChanged,
            self.number.valueChanged,
            self.frequency.textChanged,
        ):
            # noinspection PyUnresolvedReferences
            signal.connect(self.on_changed)
        self.setMinimumSize(560, 240)
        self.update_state()

    def section(self) -> dict:
        return self.model.timestepper

    def load(self) -> None:
        """
        Shows the time of the model.
        :return: None
        """
        time = self.section()
        self.start.set_text(time.get("start"))
        self.end.set_text(time.get("end"))
        timestep = time.get("timestep")
        kind = td.timestep_type(timestep) or "Days"
        value = td.timestep_value(timestep) if td.timestep_type(timestep) else None
        self.kind.setCurrentIndex(self.kind.findData(kind))
        if kind == "Frequency":
            self.frequency.setText(value if isinstance(value, str) else "")
        elif isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            self.number.setValue(value)
        self.show_timestep_widgets()

    def show_timestep_widgets(self) -> None:
        is_frequency = self.kind.currentData() == "Frequency"
        self.number.setVisible(not is_frequency)
        self.frequency.setVisible(is_frequency)
        self.number.setSuffix(" hours" if self.kind.currentData() == "Hours" else " days")

    def new_time(self) -> dict:
        """
        Returns the time section as set in the dialog. The other keys of the section
        are kept.
        :return: The dictionary.
        """
        kind = self.kind.currentData()
        value = self.frequency.text().strip() if kind == "Frequency" else self.number.value()
        return {
            **copy.deepcopy(self.section()),
            "start": self.start.text(),
            "end": self.end.text(),
            "timestep": td.make_timestep(kind, value),
        }

    @Slot()
    def on_changed(self) -> None:
        self.show_timestep_widgets()
        self.save_button.setEnabled(True)
        self.update_state()

    def update_state(self) -> list[str]:
        """
        Checks the values and shows the number of timesteps.
        :return: The problems found.
        """
        time = self.new_time()
        problems = td.validate_time(time)
        self.problems.setText("\n".join(problems))
        steps = td.count_steps(time) if not problems else None
        description = td.describe_timestep(time["timestep"])
        if problems:
            self.summary.setText("")
        elif steps is not None:
            self.summary.setText(
                f"{steps:,} timesteps of {description}, from {time['start']} to "
                f"{time['end']}"
            )
        else:
            self.summary.setText(
                f"The timestep is {description}. The number of timesteps depends "
                "on the calendar"
            )
        self.save_button.setProperty("valid", not problems)
        return problems

    @Slot()
    def save(self) -> bool:
        """
        Saves the time in the model.
        :return: True if the time was saved, False if it is not valid.
        """
        if self.update_state():
            return False
        time = self.new_time()
        self.model.json[self.model.dialect.time_key] = time
        self.model.has_changed()
        self.save_button.setEnabled(False)
        app = self.app
        if app is not None:
            if hasattr(app, "time_stepper"):
                app.time_stepper.refresh()
            if hasattr(app, "components_tree"):
                app.components_tree.reload()
            if hasattr(app, "statusBar"):
                app.statusBar().showMessage("Updated the model time")
        return True
