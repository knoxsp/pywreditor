from abc import ABC, abstractmethod
from typing import Any

"""
 A dialect handles one model file format: pywr v1 or pywr-next. The editor detects
 the dialect when a model is opened and asks it for everything that depends on the
 format. The schematic, the map, the sidecar, the shapes, the styles and the undo
 history are shared by all dialects.

 The interface grows as each part of the editor is moved behind it.
"""


class ModelDialect(ABC):
    key: str
    """ A short identifier, such as "v1" """
    label: str
    """ The name shown to the user, such as "pywr v1" """
    can_open: bool = True
    """ Whether the editor can open models in this dialect yet """

    @classmethod
    @abstractmethod
    def detect(cls, model_json: Any) -> bool:
        """
        Checks whether a model dictionary is written in this dialect.
        :param model_json: The content of the model file.
        :return: True if the model is in this dialect, False otherwise.
        """

    @abstractmethod
    def empty_model(self) -> dict:
        """
        Returns the dictionary of a new empty model.
        :return: The model dictionary.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.key!r}>"
