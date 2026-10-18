from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    QUrl,
    Slot,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.model.results import (
    ENVELOPE_PERCENTILES,
    MAX_INDIVIDUAL_TRACES,
    ResultsRun,
    Trace,
    choose_plot_mode,
    default_ticked,
    envelope,
    list_runs,
    trace_statistics,
)
from pywr_editor.style import AppStylesheet


class FrameModel(QAbstractTableModel):
    """Shows a pandas dataframe. The data is read lazily, so wide tables are fine."""

    def __init__(self, frame: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self.frame = frame if frame is not None else pd.DataFrame()

    def set_frame(self, frame: pd.DataFrame) -> None:
        self.beginResetModel()
        self.frame = frame
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.frame.index)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            value = self.frame.iat[index.row(), index.column()]
            if isinstance(value, (float, np.floating)):
                return "" if np.isnan(value) else f"{value:.6g}"
            return str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self.frame.columns[section])
        label = self.frame.index[section]
        if isinstance(label, pd.Timestamp):
            return label.strftime("%Y-%m-%d")
        return str(label)


class TraceModel(QAbstractTableModel):
    """The traces of the selected recorders, with a tick to draw them."""

    HEADERS = ["", "Trace", "Min", "Mean", "Max"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.traces: list[Trace] = []
        self.stats = pd.DataFrame()
        self.ticked: set[tuple[str, int]] = set()

    def set_traces(
        self, traces: list[Trace], stats: pd.DataFrame, ticked: set
    ) -> None:
        self.beginResetModel()
        self.traces = traces
        self.stats = stats
        self.ticked = set(ticked)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.traces)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def flags(self, index):
        flags = super().flags(index)
        if index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        trace = self.traces[index.row()]
        column = index.column()
        if column == 0 and role == Qt.ItemDataRole.CheckStateRole:
            return (
                Qt.CheckState.Checked
                if trace.key in self.ticked
                else Qt.CheckState.Unchecked
            )
        if role == Qt.ItemDataRole.DisplayRole and column == 1:
            return trace.label
        if column >= 2:
            value = self.stats.iloc[index.row(), column - 2]
            if role == Qt.ItemDataRole.DisplayRole:
                return "" if np.isnan(value) else f"{value:.6g}"
            if role == Qt.ItemDataRole.UserRole:
                # numeric sort
                return float("-inf") if np.isnan(value) else float(value)
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.UserRole and column == 1:
            return trace.label.lower()
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            key = self.traces[index.row()].key
            if Qt.CheckState(value) == Qt.CheckState.Checked:
                self.ticked.add(key)
            else:
                self.ticked.discard(key)
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def set_ticked(self, keys: set) -> None:
        self.ticked = set(keys)
        if self.traces:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.traces) - 1, 0),
                [Qt.ItemDataRole.CheckStateRole],
            )


class ResultsDialog(QDialog):
    def __init__(
        self,
        output_dir: str | Path,
        select_run: str | Path | None = None,
        parent: QWidget | None = None,
    ):
        """
        Initialises the dialog to inspect the saved results of the model runs, with
        a plot, a table of the time series and a table of the recorder values.
        :param output_dir: The folder containing the runs.
        :param select_run: The run to show. Default to the most recent one.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.output_dir = Path(output_dir)
        self.run: ResultsRun | None = None
        self.mode_choice = "auto"
        self.setWindowTitle("Results")
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(AppStylesheet().get())
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # run selection
        self.run_combo = QComboBox()
        self.run_combo.setMinimumWidth(320)
        # noinspection PyUnresolvedReferences
        self.run_combo.currentIndexChanged.connect(self.on_run_changed)
        browse = QPushButton("Open other run...")
        # noinspection PyUnresolvedReferences
        browse.clicked.connect(self.on_browse)
        open_folder = QPushButton("Show folder")
        # noinspection PyUnresolvedReferences
        open_folder.clicked.connect(self.on_open_folder)
        self.run_info = QLabel()
        top = QHBoxLayout()
        top.addWidget(QLabel("Run"))
        top.addWidget(self.run_combo)
        top.addWidget(browse)
        top.addWidget(open_folder)
        top.addWidget(self.run_info, 1)

        # recorders
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter recorders (text, or type:name)")
        self.filter.setClearButtonEnabled(True)
        # noinspection PyUnresolvedReferences
        self.filter.textChanged.connect(self.apply_recorder_filter)
        self.recorder_list = QListWidget()
        self.recorder_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        # noinspection PyUnresolvedReferences
        self.recorder_list.itemSelectionChanged.connect(self.schedule_update)
        self.recorder_count = QLabel()
        select_filtered = QPushButton("Select shown")
        select_filtered.setToolTip("Select all the recorders matching the filter")
        # noinspection PyUnresolvedReferences
        select_filtered.clicked.connect(self.recorder_list.selectAll)
        clear = QPushButton("Clear")
        # noinspection PyUnresolvedReferences
        clear.clicked.connect(self.recorder_list.clearSelection)
        recorder_buttons = QHBoxLayout()
        recorder_buttons.addWidget(select_filtered)
        recorder_buttons.addWidget(clear)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.filter)
        left_layout.addWidget(self.recorder_list, 1)
        left_layout.addLayout(recorder_buttons)
        left_layout.addWidget(self.recorder_count)

        # plot
        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.plot.setBackground("w")
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.legend = self.plot.addLegend(offset=(10, 10))
        self.plot_message = QLabel()
        self.plot_message.setWordWrap(True)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Automatic", "auto")
        self.mode_combo.addItem("Individual traces", "individual")
        self.mode_combo.addItem("Envelope (percentiles)", "envelope")
        self.mode_combo.setToolTip(
            "Individual: draw the ticked traces. Envelope: draw the median and the "
            "25-75% and 5-95% bands of all the traces, and highlight the ticked "
            "ones. Automatic uses the envelope for many scenarios of few recorders"
        )
        # noinspection PyUnresolvedReferences
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        plot_top = QHBoxLayout()
        plot_top.addWidget(QLabel("Plot"))
        plot_top.addWidget(self.mode_combo)
        plot_top.addWidget(self.plot_message, 1)
        plot_page = QWidget()
        plot_layout = QVBoxLayout(plot_page)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addLayout(plot_top)
        plot_layout.addWidget(self.plot, 1)

        # data tables
        self.data_model = FrameModel(parent=self)
        self.data_table = QTableView()
        self.data_table.setModel(self.data_model)
        self.only_ticked = QCheckBox("Only the ticked traces")
        # noinspection PyUnresolvedReferences
        self.only_ticked.toggled.connect(self.update_data_table)
        data_page = QWidget()
        data_layout = QVBoxLayout(data_page)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.addWidget(self.only_ticked)
        data_layout.addWidget(self.data_table, 1)

        self.values_model = FrameModel(parent=self)
        self.values_table = QTableView()
        self.values_table.setModel(self.values_model)

        self.tabs = QTabWidget()
        self.tabs.addTab(plot_page, "Plot")
        self.tabs.addTab(data_page, "Time series")
        self.tabs.addTab(self.values_table, "Values")

        # trace picker
        self.trace_model = TraceModel(self)
        self.trace_proxy = QSortFilterProxyModel(self)
        self.trace_proxy.setSourceModel(self.trace_model)
        self.trace_proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.trace_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.trace_proxy.setFilterKeyColumn(1)
        self.trace_model.dataChanged.connect(self.on_ticks_changed)
        self.trace_table = QTableView()
        self.trace_table.setModel(self.trace_proxy)
        self.trace_table.setSortingEnabled(True)
        self.trace_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.trace_table.horizontalHeader().setStretchLastSection(False)
        self.trace_table.horizontalHeader().setSectionResizeMode(
            1, self.trace_table.horizontalHeader().ResizeMode.Stretch
        )
        self.trace_table.setColumnWidth(0, 30)
        self.trace_filter = QLineEdit()
        self.trace_filter.setPlaceholderText("Filter traces")
        self.trace_filter.setClearButtonEnabled(True)
        # noinspection PyUnresolvedReferences
        self.trace_filter.textChanged.connect(self.trace_proxy.setFilterFixedString)
        self.trace_label = QLabel()

        buttons = [
            ("First 20", f"Tick the first {MAX_INDIVIDUAL_TRACES} traces", self.tick_first),
            ("Tick shown", "Tick the traces matching the filter", self.tick_shown),
            (
                "Tick highlighted",
                "Tick the rows selected in the table",
                self.tick_highlighted,
            ),
            ("Top 20 by max", "Tick the 20 traces with the largest maximum", self.tick_top),
            ("Untick all", "Remove all the traces from the plot", self.untick_all),
        ]
        pick_buttons = QHBoxLayout()
        pick_buttons.addWidget(QLabel("Traces"))
        pick_buttons.addWidget(self.trace_filter, 1)
        for text, tip, slot in buttons:
            button = QPushButton(text)
            button.setToolTip(tip)
            # noinspection PyUnresolvedReferences
            button.clicked.connect(slot)
            pick_buttons.addWidget(button)
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addLayout(pick_buttons)
        bottom_layout.addWidget(self.trace_table, 1)
        bottom_layout.addWidget(self.trace_label)

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.tabs)
        right.addWidget(bottom)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 1)
        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(left)
        main.addWidget(right)
        main.setStretchFactor(0, 1)
        main.setStretchFactor(1, 3)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(main, 1)

        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.setInterval(150)
        self.update_timer.timeout.connect(self.update_selection)
        self.traces: list[Trace] = []
        self.frame = pd.DataFrame()
        self.mode = "individual"

        self.load_runs(select_run)

    # runs ----------------------------------------------------------------------
    def load_runs(self, select_run: str | Path | None = None) -> None:
        """Fills the run list with the runs in the output folder."""
        runs = list_runs(self.output_dir)
        if select_run is not None and Path(select_run) not in runs:
            runs.insert(0, Path(select_run))
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        for path in runs:
            self.run_combo.addItem(path.name, str(path))
        if select_run is not None:
            index = self.run_combo.findData(str(select_run))
            self.run_combo.setCurrentIndex(max(index, 0))
        self.run_combo.blockSignals(False)
        if runs:
            self.on_run_changed()
        else:
            self.run_info.setText(f"No results found in {self.output_dir}")

    @Slot()
    def on_run_changed(self) -> None:
        path = self.run_combo.currentData()
        if not path:
            return
        try:
            self.run = ResultsRun(Path(path))
        except Exception as e:
            self.run = None
            QMessageBox.warning(self, "Results", f"Cannot read the results: {e}")
            return
        meta = self.run.metadata
        state = "completed" if meta.get("completed") else "stopped early"
        skipped = len(meta.get("skipped", {}))
        self.run_info.setText(
            f"{state}, last timestep {meta.get('last_timestep')}, "
            f"{meta.get('recorders')} recorders, solver {meta.get('solver')}"
            + (f", {skipped} could not be saved" if skipped else "")
        )
        self.recorder_list.clear()
        for name, row in self.run.index.iterrows():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, row["type"])
            if not row["file"]:
                item.setToolTip(f"{row['type']} - value only, no time series")
            else:
                item.setToolTip(f"{row['type']}, {row['traces']} traces")
            self.recorder_list.addItem(item)
        self.apply_recorder_filter()
        self.update_selection()

    @Slot()
    def on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select a run folder", str(self.output_dir)
        )
        if not folder:
            return
        if not (Path(folder) / "metadata.json").is_file():
            # the output folder itself
            self.output_dir = Path(folder)
            self.load_runs()
        else:
            self.load_runs(select_run=folder)

    @Slot()
    def on_open_folder(self) -> None:
        path = self.run_combo.currentData() or str(self.output_dir)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # recorders ------------------------------------------------------------------
    @Slot()
    def apply_recorder_filter(self) -> None:
        text = self.filter.text().strip().lower()
        shown = 0
        for i in range(self.recorder_list.count()):
            item = self.recorder_list.item(i)
            name = item.text().lower()
            kind = str(item.data(Qt.ItemDataRole.UserRole)).lower()
            if ":" in text and text.split(":", 1)[0] in kind:
                # "type:name" - the name part can be empty
                match = text.split(":", 1)[1].strip() in name
            else:
                match = text in name or text in kind
            item.setHidden(not match)
            shown += match
        self.recorder_count.setText(
            f"{shown} of {self.recorder_list.count()} recorders shown"
        )

    @Slot()
    def schedule_update(self) -> None:
        self.update_timer.start()

    def selected_recorders(self) -> list[str]:
        return [
            item.text()
            for item in self.recorder_list.selectedItems()
            if not item.isHidden()
        ]

    @Slot()
    def update_selection(self) -> None:
        """Loads the selected recorders and refreshes the tables and the plot."""
        if self.run is None:
            return
        names = self.selected_recorders()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.traces = self.run.traces(names)
            self.frame = (
                self.run.trace_data(self.traces) if self.traces else pd.DataFrame()
            )
            stats = (
                trace_statistics(self.frame)
                if self.traces
                else pd.DataFrame(columns=["min", "mean", "max"])
            )
            recorder_count = len({t.recorder for t in self.traces})
            self.auto_mode = choose_plot_mode(len(self.traces), recorder_count)
            self.trace_model.set_traces(
                self.traces,
                stats,
                default_ticked(self.traces, self.effective_mode()),
            )
            self.update_values_table(names)
            self.update_data_table()
            self.update_plot()
        finally:
            QApplication.restoreOverrideCursor()
        self.recorder_count.setText(
            self.recorder_count.text().split(";")[0]
            + f"; {len(names)} selected"
        )

    def update_values_table(self, names: list[str]) -> None:
        summary = self.run.summary
        if names:
            summary = summary[summary["recorder"].isin(names)]
        if summary.empty:
            self.values_model.set_frame(pd.DataFrame())
            return
        summary = summary.copy()
        summary["scenario"] = summary["scenario"].map(self.run.combination_label)
        table = summary.pivot_table(
            index="recorder", columns="scenario", values="value", sort=False
        )
        self.values_model.set_frame(table)

    # traces ---------------------------------------------------------------------
    def effective_mode(self) -> str:
        if self.mode_choice == "auto":
            return getattr(self, "auto_mode", "individual")
        return self.mode_choice

    @Slot()
    def on_mode_changed(self) -> None:
        self.mode_choice = self.mode_combo.currentData()
        # the default ticks depend on the mode
        self.trace_model.set_ticked(default_ticked(self.traces, self.effective_mode()))
        self.update_plot()

    @Slot()
    def on_ticks_changed(self) -> None:
        self.update_plot()
        self.update_data_table()

    def _visible_keys(self) -> list[tuple[str, int]]:
        return [
            self.trace_model.traces[
                self.trace_proxy.mapToSource(self.trace_proxy.index(row, 0)).row()
            ].key
            for row in range(self.trace_proxy.rowCount())
        ]

    @Slot()
    def tick_first(self) -> None:
        self.trace_model.set_ticked(default_ticked(self.traces, "individual"))
        self.on_ticks_changed()

    @Slot()
    def tick_shown(self) -> None:
        keys = self._visible_keys()
        if len(keys) > 200:
            answer = QMessageBox.question(
                self,
                "Tick traces",
                f"Drawing {len(keys)} lines is slow and hard to read. "
                "Do you want to continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.trace_model.set_ticked(set(keys))
        self.on_ticks_changed()

    @Slot()
    def tick_highlighted(self) -> None:
        keys = set(self.trace_model.ticked)
        for index in self.trace_table.selectionModel().selectedRows():
            source = self.trace_proxy.mapToSource(index)
            keys.add(self.trace_model.traces[source.row()].key)
        self.trace_model.set_ticked(keys)
        self.on_ticks_changed()

    @Slot()
    def tick_top(self) -> None:
        stats = self.trace_model.stats
        if stats.empty:
            return
        order = stats["max"].fillna(-np.inf).to_numpy().argsort()[::-1]
        top = {self.traces[i].key for i in order[:MAX_INDIVIDUAL_TRACES]}
        self.trace_model.set_ticked(top)
        self.on_ticks_changed()

    @Slot()
    def untick_all(self) -> None:
        self.trace_model.set_ticked(set())
        self.on_ticks_changed()

    # views ----------------------------------------------------------------------
    def ticked_traces(self) -> list[Trace]:
        return [t for t in self.traces if t.key in self.trace_model.ticked]

    @Slot()
    def update_data_table(self) -> None:
        if not self.traces:
            self.data_model.set_frame(pd.DataFrame())
        elif self.only_ticked.isChecked():
            ticked = [t.label for t in self.ticked_traces()]
            self.data_model.set_frame(self.frame[ticked])
        else:
            self.data_model.set_frame(self.frame)

    @staticmethod
    def _seconds(index: pd.Index) -> np.ndarray:
        return np.asarray(pd.DatetimeIndex(index).astype("int64") / 1e9)

    def update_plot(self) -> None:
        self.plot.clear()
        self.legend.clear()
        total = len(self.traces)
        ticked = self.ticked_traces()
        self.trace_label.setText(
            f"{total} traces, {len(ticked)} ticked. Click a column header to sort, "
            "for example by Max."
        )
        if total == 0:
            self.plot_message.setText(
                "Select one or more recorders on the left to plot them."
            )
            return

        mode = self.effective_mode()
        x = self._seconds(self.frame.index)
        message = []
        if mode == "envelope":
            recorders = sorted({t.recorder for t in self.traces})
            # one band for each recorder, unless there are too many to read
            groups = (
                {r: [t.label for t in self.traces if t.recorder == r] for r in recorders}
                if len(recorders) <= MAX_INDIVIDUAL_TRACES
                else {f"All {total} traces": list(self.frame.columns)}
            )
            for i, (name, columns) in enumerate(groups.items()):
                env = envelope(self.frame[columns])
                colour = pg.intColor(i, hues=max(len(groups), 3))
                lo5 = pg.PlotDataItem(x, env[5].to_numpy())
                hi95 = pg.PlotDataItem(x, env[95].to_numpy())
                lo25 = pg.PlotDataItem(x, env[25].to_numpy())
                hi75 = pg.PlotDataItem(x, env[75].to_numpy())
                light, dark = pg.mkColor(colour), pg.mkColor(colour)
                light.setAlpha(40)
                dark.setAlpha(90)
                self.plot.addItem(pg.FillBetweenItem(lo5, hi95, brush=light))
                self.plot.addItem(pg.FillBetweenItem(lo25, hi75, brush=dark))
                self.plot.plot(
                    x,
                    env[50].to_numpy(),
                    pen=pg.mkPen(colour, width=3),
                    name=f"{name} (median, {len(columns)} traces)",
                )
            message.append(
                f"Envelope of {total} traces: median line, 25-75% and 5-95% bands."
            )
            if len(self.traces) and len({t.recorder for t in self.traces}) > 1:
                message.append("Bands are per recorder.")
        else:
            if total > MAX_INDIVIDUAL_TRACES:
                message.append(
                    f"{total} traces: showing the {len(ticked)} ticked. Tick others in "
                    "the table below, or use the envelope for many scenarios."
                )

        # the ticked traces: all the lines in individual mode, a highlight in
        # envelope mode
        for i, trace in enumerate(ticked):
            self.plot.plot(
                x,
                self.frame[trace.label].to_numpy(dtype=float),
                pen=pg.mkPen(
                    pg.intColor(i, hues=max(min(len(ticked), 20), 3)),
                    width=2 if mode == "individual" else 1,
                    style=Qt.PenStyle.SolidLine
                    if mode == "individual"
                    else Qt.PenStyle.DashLine,
                ),
                name=trace.label if mode == "individual" and len(ticked) <= 20 else None,
            )
        if len(ticked) > 20:
            message.append("Legend hidden: more than 20 lines.")
        self.plot_message.setText(" ".join(message))


__all__ = ["ResultsDialog", "ENVELOPE_PERCENTILES"]
