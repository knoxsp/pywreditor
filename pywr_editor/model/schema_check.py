import os
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from pywr_editor.model.validation import _leaf_error, _shorten

"""
 Checks a value against a part of a JSON Schema, for the forms of any dialect. The
 forms use it to refuse a value that the schema rejects, and it is the same check the
 validation of the whole model makes, so the form and the validation dialog agree. The
 messages say what the schema requires in words, instead of repeating the value.
"""

TYPE_NAMES = {
    "integer": "a whole number",
    "number": "a number",
    "string": "text",
    "boolean": "true or false",
    "array": "a list",
    "object": "an object",
    "null": "empty",
}


@dataclass(frozen=True)
class SchemaIssue:
    """A value that the schema rejects."""

    message: str
    path: tuple[str | int, ...] = ()
    """ Where the problem is in the checked value (empty if it is the value itself) """


def _number(value: Any) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _type_text(expected: Any) -> str:
    types = expected if isinstance(expected, list) else [expected]
    return " or ".join(TYPE_NAMES.get(t, str(t)) for t in types if t != "null")


def friendly_message(error: Any) -> str:
    """
    Describes in words why a value is rejected.
    :param error: The (leaf) jsonschema validation error.
    :return: The message.
    """
    validator, expected = error.validator, error.validator_value
    where = "The value"
    if error.absolute_path:
        where = f'"{error.absolute_path[-1]}"' if isinstance(
            error.absolute_path[-1], str
        ) else "The item"
    if validator == "type":
        return f"{where} must be {_type_text(expected)}"
    if validator == "minimum":
        return f"{where} must be at least {_number(expected)}"
    if validator == "exclusiveMinimum":
        return f"{where} must be greater than {_number(expected)}"
    if validator == "maximum":
        return f"{where} must be at most {_number(expected)}"
    if validator == "exclusiveMaximum":
        return f"{where} must be less than {_number(expected)}"
    if validator == "enum":
        return f"{where} must be one of: " + ", ".join(str(v) for v in expected)
    if validator == "const":
        return f"{where} must be {expected}"
    if validator == "minItems":
        return f"The list must have at least {expected} item" + (
            "" if expected == 1 else "s"
        )
    if validator == "maxItems":
        return f"The list must have at most {expected} item" + (
            "" if expected == 1 else "s"
        )
    if validator == "pattern":
        return f"{where} does not have the expected format"
    return _shorten(error.message)


class SchemaChecker:
    """Checks values against parts of a schema that has shared definitions."""

    def __init__(self, defs: dict):
        """
        :param defs: The "$defs" of the schema, which "$ref" values point to.
        """
        self.defs = defs

    def validator(self, schema: dict) -> Draft202012Validator:
        """
        Returns a validator for a part of the schema.
        :param schema: The schema of the value, which may use "$ref".
        :return: The validator.
        """
        return Draft202012Validator({**schema, "$defs": self.defs})

    def check(self, schema: dict, value: Any) -> list[SchemaIssue]:
        """
        Finds why the schema rejects a value.
        :param schema: The schema of the value.
        :param value: The value.
        :return: The issues, none if the value is valid. Each branch of a choice
        between types is not reported: only the closest one.
        """
        issues = []
        for error in sorted(
            self.validator(schema).iter_errors(value),
            key=lambda e: [str(p) for p in e.absolute_path],
        ):
            leaf = _leaf_error(error) if error.context else error
            path = tuple(leaf.absolute_path)
            if leaf.validator == "additionalProperties" and isinstance(leaf.instance, dict):
                # one issue for each property, so that a property added later does not
                # change the others
                allowed = set(leaf.schema.get("properties", {}))
                for key in leaf.instance:
                    if key not in allowed:
                        issues.append(
                            SchemaIssue(f'"{key}" is not allowed here', path + (key,))
                        )
                continue
            issues.append(SchemaIssue(friendly_message(leaf), path))
        return issues

    def is_valid(self, schema: dict, value: Any) -> bool:
        """
        Checks whether the schema accepts a value.
        :param schema: The schema of the value.
        :param value: The value.
        :return: True if it does.
        """
        return self.validator(schema).is_valid(value)


def new_issues(
    before: list[SchemaIssue], after: list[SchemaIssue]
) -> list[SchemaIssue]:
    """
    Finds the issues that appeared after a change.
    :param before: The issues before the change.
    :param after: The issues after the change.
    :return: The issues in after that are not in before.
    """
    known = {(issue.path, issue.message) for issue in before}
    return [issue for issue in after if (issue.path, issue.message) not in known]


def missing_file_message(path: Any, model_file: str | None) -> str | None:
    """
    Checks that a file named in the model exists. This is not a schema rule, but the
    model cannot be run without the file.
    :param path: The path, relative to the folder of the model or absolute. Addresses
    (such as "https://...") are not checked.
    :param model_file: The path of the model file, None if the model is not saved.
    :return: The warning, or None if the file exists or cannot be checked.
    """
    if not isinstance(path, str) or not path.strip() or "://" in path:
        return None
    if model_file is None:
        return None
    full_path = os.path.join(os.path.dirname(os.path.abspath(model_file)), path)
    if os.path.exists(full_path):
        return None
    return f'The file "{path}" does not exist'
