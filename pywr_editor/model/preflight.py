import copy
import time
import traceback

from PySide6.QtCore import QObject, Signal, Slot

from pywr_editor.model.pywr_worker import apply_solver, load_pywr_model
from pywr_editor.utils import Logging

"""
 Loads and sets up the model with pywr, without stepping it. This uses the same
 pywr version, Python paths, imports, solver and model file as a run, so the errors
 are those the run would show. A successful preflight does not guarantee that every
 time-step solves.
"""


class PreflightWorker(QObject):
    finished = Signal(object, float)
    """ Signal emitted when the check ends. It returns the exception traceback
    (None when the model loads and sets up) and the elapsed seconds """

    def __init__(
        self,
        model_dict: dict,
        model_file: str,
        python_paths: list[str] | None = None,
        python_modules: list[str] | None = None,
        solver: str | None = None,
    ):
        """
        Initialises the worker.
        :param model_dict: The model dictionary. A copy is loaded as pywr may change
        the dictionary.
        :param model_file: The absolute path to the model file.
        :param python_paths: The folders added to the Python search path.
        :param python_modules: The modules to import before loading the model.
        :param solver: The solver name, used when the model does not set one.
        """
        super().__init__()
        self.logger = Logging().logger(self.__class__.__name__)
        self.model_dict = apply_solver(copy.deepcopy(model_dict), solver)
        self.model_file = model_file
        self.python_paths = python_paths
        self.python_modules = python_modules

    @Slot()
    def run(self) -> None:
        """
        Loads and sets up the model.
        :return: None
        """
        start = time.perf_counter()
        error = None
        # noinspection PyBroadException
        try:
            model = load_pywr_model(
                self.model_dict,
                self.model_file,
                self.python_paths,
                self.python_modules,
                self.logger,
            )
            model.setup()
        except Exception:
            error = traceback.format_exc()
            self.logger.debug(f"Preflight failed because: {error}")
        # noinspection PyUnresolvedReferences
        self.finished.emit(error, time.perf_counter() - start)
