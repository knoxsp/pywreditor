from typing import Any

"""
 The editor keeps the appearance of a pywr-next node (its colour, size, style and the
 colour of its edges) in the "tags" of the node's "meta", under keys that start with
 "editor:". Tags are part of the pywr-next schema (a map of strings), so this data is
 valid, is kept by pywr-next and travels with the model. The values are strings.
"""

PREFIX = "editor:"
""" The start of the tag keys used by the editor """


def tag_key(key: str) -> str:
    """
    Returns the tag key of an editor value.
    :param key: The editor key, such as "node_color".
    :return: The tag key, such as "editor:node_color".
    """
    return f"{PREFIX}{key}"


def read_tag(tags: Any, key: str) -> str | None:
    """
    Reads an editor value from the tags of a component.
    :param tags: The tags dictionary.
    :param key: The editor key, such as "node_color".
    :return: The value or None if it is not set.
    """
    if not isinstance(tags, dict):
        return None
    value = tags.get(tag_key(key))
    return value if isinstance(value, str) else None


def write_tag(tags: dict, key: str, value: Any) -> None:
    """
    Writes an editor value in the tags of a component. The value is stored as a string.
    :param tags: The tags dictionary, changed in place.
    :param key: The editor key, such as "node_size".
    :param value: The value. None removes the tag.
    :return: None
    """
    if value is None:
        tags.pop(tag_key(key), None)
    else:
        tags[tag_key(key)] = str(value)
