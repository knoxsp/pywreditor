from functools import partial
from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import QDate, Qt, Slot
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

from pywr_editor.style import Color, Theme
from pywr_editor.widgets import DateEdit, SpinBox

if TYPE_CHECKING:
    from pywr_editor import MainWindow


class TimeStepperWidget(QWidget):
    def __init__(self, parent: "MainWindow"):
        """
        Initialises the widget.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.app = parent
        self.model_config = parent.model_config

        self.running = False
        self.editable = True
        main_layout = QGridLayout()
        main_layout.setRowMinimumHeight(0, 40)

        # start date
        main_layout.addWidget(QLabel("Start date"), 0, 0)
        start_date = DateEdit(self.model_config.start_date)
        start_date.setObjectName("start_date")
        # noinspection PyUnresolvedReferences
        start_date.dateChanged.connect(partial(self.date_changed, "start_date"))
        main_layout.addWidget(start_date, 0, 1)

        # end date
        main_layout.addWidget(QLabel("End date"), 1, 0)
        end_date = DateEdit(self.model_config.end_date)
        end_date.setObjectName("end_date")
        # noinspection PyUnresolvedReferences
        end_date.dateChanged.connect(partial(self.date_changed, "end_date"))
        main_layout.addWidget(end_date, 1, 1)

        # timestep
        main_layout.addWidget(QLabel("Timestep"), 0, 3)
        time_step = SpinBox()
        time_step.setValue(self.model_config.time_delta)
        time_step.setRange(1, 365)
        time_step.setSuffix(" days")
        time_step.setObjectName("time_step")
        Theme.bind(
            time_step,
            lambda w: "#time_step { padding: 2px; border: 1px solid "
            + Color("gray", 400).hex
            + "}",
        )
        # noinspection PyUnresolvedReferences
        time_step.valueChanged.connect(self.time_step_changed)
        main_layout.addWidget(time_step, 0, 4)

        # run to date
        main_layout.addWidget(QLabel("Run to date"), 1, 3)
        saved_run_to_date = parent.editor_settings.run_to_date
        if saved_run_to_date is None:
            saved_run_to_date = self.model_config.end_date
        run_to_date = DateEdit(saved_run_to_date)
        run_to_date.setObjectName("run_to_date")
        # noinspection PyUnresolvedReferences
        run_to_date.dateChanged.connect(
            lambda date: parent.editor_settings.save_run_to_date(
                date.toString("yyyy-MM-dd")
            )
        )
        main_layout.addWidget(run_to_date, 1, 4)

        # separator
        separator = QWidget()
        separator.setFixedHeight(60)
        separator.setFixedWidth(1)
        separator.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        Theme.bind(
            separator,
            lambda w: f"background-color: {Color('gray', 300).hex}",
        )
        main_layout.addWidget(separator, 0, 2, 0, 1, Qt.AlignmentFlag.AlignHCenter)
        main_layout.setColumnMinimumWidth(2, 15)

        self.setLayout(main_layout)
        self.start_date = start_date
        self.end_date = end_date
        self.time_step = time_step
        self.run_to_date = run_to_date
        self.refresh()

    def refresh(self) -> None:
        """
        Shows the time of the model, after the dialog that edits it saved it. When the
        model has a time of day or a timestep that is not a number of days, which the
        toolbar cannot edit, the fields are disabled.
        :return: None
        """
        time = self.model_config.timestepper
        dialect = self.model_config.dialect
        self.editable = dialect.simple_time(time)
        for widget, key in ((self.start_date, "start"), (self.end_date, "end")):
            date = QDate.fromString(str(time.get(key))[:10], "yyyy-MM-dd")
            if date.isValid():
                widget.blockSignals(True)
                widget.setDate(date)
                widget.blockSignals(False)
        self.time_step.blockSignals(True)
        self.time_step.setValue(self.model_config.time_delta)
        self.time_step.blockSignals(False)
        self.apply_enabled()

    def set_running(self, is_running: bool) -> None:
        """
        Disables the fields while the model runs.
        :param is_running: Whether the model is running.
        :return: None
        """
        self.running = is_running
        self.apply_enabled()

    def apply_enabled(self) -> None:
        editable = self.editable and not self.running
        for widget in (self.start_date, self.end_date, self.time_step):
            widget.setEnabled(editable)
            widget.setToolTip(
                ""
                if self.editable
                else "The time of this model is edited with the Time button of the "
                "Model tab"
            )
        self.run_to_date.setDisabled(self.running)

    @Slot(QDate)
    def date_changed(
        self,
        date_type: Literal["start_date", "end_date"],
        date: QDate,
    ) -> None:
        """
        Updates the timestepper dates in the model when the date field is changed.
        :param date_type: The changed date ("start_date" or "end_date").
        :param date: The new date.
        :return: None
        """
        date_str = date.toString("yyyy-MM-dd")
        if date_type == "start_date":
            self.model_config.start_date = date_str
        elif date_type == "end_date":
            self.model_config.end_date = date_str
        else:
            raise ValueError("date_type can only be 'start_date' or 'end_date'")

    @Slot(int)
    def time_step_changed(
        self,
        step: int,
    ) -> None:
        """
        Updates the timestepper timestep in the model when the field is changed.
        :param step: The timestep as number of days.
        :return: None
        """
        self.model_config.time_delta = step
        self.app.components_tree.reload()
