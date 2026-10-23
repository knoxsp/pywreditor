import importlib
import site
import sys
import traceback
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import TypedDict

import pandas as pd
import pywr
from pandas import Timestamp
from PySide6.QtCore import QMutex, QObject, QWaitCondition, Signal
from pywr.model import Model

from pywr_editor.model.results import export_results
from pywr_editor.utils import Logging


def add_python_paths(paths: list[str]) -> list[str]:
    """
    Makes the folders importable. A virtual environment (or any folder containing
    a "site-packages" folder) is added through its site-packages folder.
    :param paths: The folders to add.
    :return: The folders that were added to sys.path.
    """
    added = []
    for path in paths:
        folder = Path(path).expanduser()
        if not folder.is_dir():
            continue
        # Linux/macOS: lib/pythonX.Y/site-packages. Windows: Lib/site-packages. Only
        # the running Python version is used, as packages are not portable
        version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        site_dirs = [
            d
            for d in [
                folder / "lib" / version / "site-packages",
                folder / "Lib" / "site-packages",
                folder / "site-packages",
            ]
            if d.is_dir()
        ]
        for d in site_dirs or [folder]:
            if str(d) not in sys.path:
                if site_dirs:
                    # also processes .pth files
                    site.addsitedir(str(d))
                else:
                    sys.path.insert(0, str(d))
                added.append(str(d))
    return added


def apply_solver(model_dict: dict, solver: str | None) -> dict:
    """
    Sets the solver in the model dictionary if the model does not set its own.
    :param model_dict: The model dictionary.
    :param solver: The solver name (e.g. "glpk-edge").
    :return: The dictionary to load. This is a copy if the solver is set, as the
    dictionary is owned by the editor.
    """
    if solver and "solver" not in model_dict:
        return {**model_dict, "solver": {"name": solver}}
    return model_dict


def release_solver(model: Model | None) -> None:
    """
    Frees the solver of a model. GLPK keeps its memory allocator per thread, so the
    solver must be freed by the thread that created it. Otherwise the garbage
    collector frees it later in another thread (typically the GUI thread) and GLPK
    aborts the process ("Error detected in file env/alloc.c"). This happens on Windows
    and macOS. Dropping the last reference frees the solver straight away, with no need
    to collect the garbage.
    :param model: The pywr model.
    :return: None
    """
    if model is None:
        return
    # noinspection PyBroadException
    try:
        model.solver = None
    except Exception:
        pass


def load_pywr_model(
    model_dict: dict,
    model_file: str,
    python_paths: list[str] | None = None,
    python_modules: list[str] | None = None,
    logger=None,
) -> Model:
    """
    Loads the model with pywr. This is used to run the model and to check that it
    loads before running it.
    :param model_dict: The model dictionary, with the solver already set.
    :param model_file: The absolute path to the model file, used by pywr to resolve
    relative files.
    :param python_paths: Folders or virtual environments to add to the Python
    search path so that custom components can be imported.
    :param python_modules: Modules imported before the model is loaded, so that
    the custom components they define are registered with Pywr.
    :param logger: The logger.
    :return: The pywr model. Any exception is raised.
    """
    added = add_python_paths(python_paths or [])
    if added and logger:
        logger.debug(f"Added to the Python path: {added}")
    for module in python_modules or []:
        # accept a file name such as "parameters.py"
        module = module.strip().removesuffix(".py")
        if logger:
            logger.debug(f"Importing module {module}")
        importlib.import_module(module)
    # noinspection PyArgumentList
    return Model.load(data=model_dict, path=model_file)


class RunMode(Enum):
    STEP = 0
    """ Run Model.step() """
    RUN_TO = 1
    """ Run Model.step() in a loop until the Run-to date """
    RUN = 2
    """ Run Model.step() in a loop until the end date """


class PywrProgress(TypedDict):
    current_timestamp: Timestamp
    """ Current model timestamp as pywr.Timestamp instance """
    current_index: int
    """ Current timestep index """
    last_index: int
    """ Last index of the run """


class PywrWorker(QObject):
    progress_update = Signal(PywrProgress)
    """ Signal with the dictionary containing the information for the current step """
    status_update = Signal(str)
    """ Signal emitted when the run status is updated """
    before_step = Signal()
    """ Signal emitted just before the worker runs Model.step() """
    step_done = Signal()
    """ The worker has run Model.step() """
    before_run_to = Signal()
    """ Signal emitted just before the worker runs Model.step() in loop to reach the
    'Run to' date """
    run_to_done = Signal()
    """ The worker has run the model up to the provided date """
    before_run = Signal()
    """ Signal emitted just before the worker runs Model.step() in loop to reach the
    end date """
    run_done = Signal()
    """ The worker has run the model to the end date """
    finished = Signal()
    """ Signal emitted when the worker has finished running and it instance is not
    needed anymore """
    model_error = Signal(str)
    """ Signal emitted when the model fails to load or run """
    run_to_date_reached = Signal()
    """ Signal emitted when the run-to date is reached """
    end_date_reached = Signal()
    """ Signal emitted when the end date is reached """
    results_saved = Signal(str)
    """ Signal emitted with the folder of the results, when they have been saved """
    results_error = Signal(str)
    """ Signal emitted when the results cannot be saved """

    def __init__(
        self,
        model_dict: dict,
        model_file: str,
        end_date: pd.Timestamp,
        run_to_date: pd.Timestamp,
        python_paths: list[str] | None = None,
        python_modules: list[str] | None = None,
        solver: str | None = None,
        results_dir: str | None = None,
    ):
        """
        Initialises the worker to run the pywr model.
        :param model_dict: The dictionary containing the model.
        :param model_file: The absolute path to the model file. This is used
        to let pywr resolve relative files in the JSON file.
        :param end_date: The end date of the run.
        :param run_to_date: The run-to date.
        :param python_paths: Folders or virtual environments to add to the Python
        search path so that custom parameters, nodes and recorders can be imported.
        :param python_modules: Modules imported before the model is loaded, so that
        the custom components they define are registered with Pywr.
        :param solver: The solver name (e.g. "glpk-edge"). It is only used when the
        model does not set its own "solver" key.
        :param results_dir: The folder where the recorder results are saved, in a
        timestamped subfolder, when the run ends or is stopped. Results are not
        saved if None.
        """
        super().__init__()
        self.logger = Logging().logger(self.__class__.__name__)
        self.logger.debug("Init thread")
        self.end_date = end_date
        self.run_to_date = run_to_date
        self.python_paths = python_paths or []
        self.python_modules = python_modules or []
        self.results_dir = results_dir
        self._run_failed = False
        self._last_index: int | None = None
        model_dict = apply_solver(model_dict, solver)

        self.mode: RunMode | None = None
        self.model_config = model_dict
        self.model_file = model_file
        # this applies for the Run-to or Run mode
        self._run_end_date: Timestamp | None = None
        self.pywr_model: Model | None = None

        self.is_paused = False
        self.is_killed = False
        self.paused_cond = QWaitCondition()
        self.mutex = QMutex()

    def run(self) -> None:
        """
        Runs the model.
        :return: None
        """
        # Load the model first and check if it fails
        # noinspection PyBroadException
        try:
            self.logger.debug(f"Loading model. Using pywr-{pywr.__version__}")
            self.status_update.emit("Loading model")
            self.pywr_model: Model = load_pywr_model(
                self.model_config,
                self.model_file,
                self.python_paths,
                self.python_modules,
                self.logger,
            )
            # noinspection PyUnresolvedReferences
            last_index = len(self.pywr_model.timestepper) - 1
            self._last_index = last_index
        except Exception:
            e = traceback.format_exc()
            self.logger.debug(f"Pywr failed to load because: {e}")
            self.model_error.emit(e)
            # stop the thread
            self.is_killed = True

        # start the worker loop
        current_timestep = None
        while self.is_killed is False:
            if current_timestep:
                # pause the model in Run-to and Step mode at last time step so that the
                # time-step results are available. The run must be manually stopped.
                if current_timestep.index == last_index and self.mode != RunMode.RUN:
                    self.end_date_reached.emit()

                # model is past the run-to date
                if current_timestep.period.to_timestamp() >= self.run_to_date:
                    self.run_to_date_reached.emit()

                # stop the thread when the last timestep has been reached only in Run
                # mode
                if current_timestep.index >= last_index:
                    self.logger.debug("Last timestep reached")
                    if self.mode == RunMode.RUN:
                        self.kill()
                        break

            # pause the thread loop
            self.mutex.lock()
            if self.is_paused:
                self.paused_cond.wait(self.mutex)
            self.mutex.unlock()

            if self.mode == RunMode.STEP:
                self.before_step.emit()
                self.logger.debug("Stepping")
                # noinspection PyBroadException
                try:
                    with CaptureSolverOutput() as solver_output:
                        self.pywr_model.step()
                except Exception:
                    e = self.format_error_message(
                        str(traceback.format_exc()), solver_output
                    )
                    self.logger.debug(f"Pywr failed to step because: {e}")
                    self.model_error.emit(e)
                    self._run_failed = True
                    self.finished.emit()
                    # exit worker loop
                    break

                # noinspection PyUnresolvedReferences
                current_timestep = self.pywr_model.timestepper.current

                self.logger.debug(
                    f"Stepped to {current_timestep} ({current_timestep.index + 1}"
                    + f"/{last_index + 1})"
                )
                self.step_done.emit()
                self.progress_update.emit(
                    PywrProgress(
                        current_timestamp=current_timestep.period.to_timestamp(),
                        current_index=current_timestep.index,
                        last_index=last_index,
                    )
                )
                self.pause()
            elif self.mode in [RunMode.RUN_TO, RunMode.RUN] and self._run_end_date:
                if self.mode == RunMode.RUN_TO:
                    self.before_run_to.emit()
                else:
                    self.before_run.emit()

                if current_timestep:
                    self.logger.debug(
                        f"Running from {current_timestep.period} to "
                        + f"{self._run_end_date}"
                    )
                else:
                    self.logger.debug(f"Running from start to {self._run_end_date}")

                # run the model until the Run to or End date date
                failed = False
                while not (
                    current_timestep
                    and (
                        (current_timestep.index >= last_index)
                        or current_timestep.period.to_timestamp() >= self._run_end_date
                    )
                ):
                    # noinspection PyBroadException
                    try:
                        with CaptureSolverOutput() as solver_output:
                            self.pywr_model.step()
                    except Exception:
                        e = self.format_error_message(
                            str(traceback.format_exc()), solver_output
                        )
                        self.logger.debug(f"Pywr failed to step because: {e}")
                        self.model_error.emit(e)
                        self._run_failed = True
                        self.finished.emit()
                        failed = True
                        break

                    # noinspection PyUnresolvedReferences
                    current_timestep = self.pywr_model.timestepper.current
                    self.progress_update.emit(
                        PywrProgress(
                            current_timestamp=current_timestep.period.to_timestamp(),
                            current_index=current_timestep.index,
                            last_index=last_index,
                        )
                    )

                # exit worker loop
                if failed:
                    break

                self.logger.debug(
                    f"Run to {current_timestep} ({current_timestep.index + 1}"
                    + f"/{last_index + 1})"
                )
                if self.mode == RunMode.RUN_TO:
                    self.run_to_done.emit()
                else:
                    self.run_done.emit()

                # pause the model when Run-to and the date is less or equal to the end
                # date to let the user inspect the results. In Run mode the model is
                # stopped.
                if self.mode == RunMode.RUN_TO and current_timestep.index <= last_index:
                    self.pause()

        self.save_results(current_timestep)

        # do not force a garbage collection from this thread: it can destroy Qt
        # objects outside the GUI thread and crash the application
        release_solver(self.pywr_model)
        del self.pywr_model
        self.finished.emit()
        self.pywr_model = None

    def save_results(self, current_timestep) -> None:
        """
        Saves the recorders of the model to a timestamped folder. Nothing is saved if
        no output folder is set, the model failed or it did not run any timestep.
        :param current_timestep: The last timestep run by the model.
        :return: None
        """
        if (
            not self.results_dir
            or self.pywr_model is None
            or current_timestep is None
            or self._run_failed
        ):
            return
        # noinspection PyBroadException
        try:
            self.status_update.emit("Saving results")
            run_dir = export_results(
                self.pywr_model,
                self.results_dir,
                model_file=self.model_file,
                completed=self._last_index is not None
                and current_timestep.index >= self._last_index,
            )
            self.logger.debug(f"Results saved to {run_dir}")
            self.results_saved.emit(str(run_dir))
        except Exception:
            e = traceback.format_exc()
            self.logger.debug(f"Results could not be saved because: {e}")
            self.results_error.emit(e)

    def pause(self) -> None:
        """
        Pauses the worker loop and resets its status.
        :return: None
        """
        self.mutex.lock()
        self.is_paused = True
        self.mode = None
        self._run_end_date = None
        self.mutex.unlock()

    def resume(self) -> None:
        """
        Resumes the thread execution.
        :return: None
        """
        self.mutex.lock()
        self.is_paused = False
        self.mode = None
        self.mutex.unlock()
        self.paused_cond.wakeAll()

    def step(self) -> None:
        """
        Increase the model timestep by one. This resumes
        the thread if it was previously paused.
        :return: None
        """
        if self.is_paused:
            self.resume()

        self.mutex.lock()
        self.mode = RunMode.STEP
        self.mutex.unlock()

    def run_to(self) -> None:
        """
        Runs the model until the provided date.
        :return: None
        """
        if self.is_paused:
            self.resume()

        self.mutex.lock()
        self.mode = RunMode.RUN_TO
        self._run_end_date = self.run_to_date
        self.mutex.unlock()

    def full_run(self) -> None:
        """
        Runs the model to the end date.
        :return: None
        """
        if self.is_paused:
            self.resume()

        self.mutex.lock()
        self.mode = RunMode.RUN
        self._run_end_date = self.end_date
        self.mutex.unlock()

    def kill(self) -> None:
        """
        Stops the thread.
        :return: None
        """
        if self.is_paused:
            self.resume()

        self.mutex.lock()
        self.is_killed = True
        self.mutex.unlock()

    @staticmethod
    def format_error_message(e: str, solver_output: list[str]) -> str:
        """
        Formats the exception message with the output from the solver.
        :param e: The exception stack trace.
        :param solver_output: The solver output as list of strings.
        :return: The formatted message.
        """
        if solver_output:
            e += "------------------------\nSolver output:\n"
            e += "\n".join(solver_output)
        return e


class CaptureSolverOutput(list):
    """
    Captures the stdout. This is used to capture
    the print statement output from the solver.
    """

    def __enter__(self):
        self._stdout = sys.stdout
        sys.stdout = self._stringio = StringIO()
        return self

    def __exit__(self, *args):
        self.extend(self._stringio.getvalue().splitlines())
        del self._stringio  # free up some memory
        sys.stdout = self._stdout
