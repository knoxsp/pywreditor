from typing import Any

from pywr_editor.dialects.base import ModelDialect
from pywr_editor.dialects.next import NextDialect
from pywr_editor.dialects.v1 import V1Dialect

DIALECTS: list[ModelDialect] = [NextDialect(), V1Dialect()]
""" The dialects, checked in this order. The last one is the fallback """


def detect_dialect(model_json: Any) -> ModelDialect:
    """
    Returns the dialect of a model.
    :param model_json: The content of the model file.
    :return: The dialect. Models in an unknown format are read as pywr v1 models.
    """
    for dialect in DIALECTS:
        if dialect.detect(model_json):
            return dialect
    return DIALECTS[-1]


def get_dialect(key: str) -> ModelDialect:
    """
    Returns a dialect from its key.
    :param key: The dialect key, such as "v1" or "next".
    :return: The dialect.
    """
    for dialect in DIALECTS:
        if dialect.key == key:
            return dialect
    raise KeyError(f"Unknown model dialect {key!r}")
