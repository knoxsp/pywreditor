import pytest

from pywr_editor.model.schema_check import (
    SchemaChecker,
    SchemaIssue,
    missing_file_message,
    new_issues,
)

DEFS = {
    "Colour": {"enum": ["red", "blue"]},
    "Pair": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
    "Shape": {
        "oneOf": [
            {
                "type": "object",
                "properties": {"type": {"const": "Circle"}, "radius": {"type": "number", "minimum": 0}},
                "required": ["type", "radius"],
            },
            {
                "type": "object",
                "properties": {"type": {"const": "Square"}, "side": {"type": "number"}},
                "required": ["type", "side"],
            },
        ]
    },
}
checker = SchemaChecker(DEFS)


@pytest.mark.parametrize(
    "schema, value, message",
    [
        ({"type": "number"}, "abc", "The value must be a number"),
        ({"type": "integer"}, 1.5, "The value must be a whole number"),
        ({"type": "string"}, 3, "The value must be text"),
        ({"type": "boolean"}, "yes", "The value must be true or false"),
        ({"type": "array"}, "abc", "The value must be a list"),
        ({"type": ["number", "null"]}, "abc", "The value must be a number"),
        ({"type": "number", "minimum": 1}, 0, "The value must be at least 1"),
        ({"type": "number", "minimum": 0.5}, 0, "The value must be at least 0.5"),
        ({"type": "number", "exclusiveMinimum": 0}, 0, "The value must be greater than 0"),
        ({"type": "number", "maximum": 10}, 11, "The value must be at most 10"),
        ({"type": "number", "exclusiveMaximum": 10}, 10, "The value must be less than 10"),
        ({"$ref": "#/$defs/Colour"}, "green", "The value must be one of: red, blue"),
        ({"const": "a"}, "b", "The value must be a"),
        ({"$ref": "#/$defs/Pair"}, [1], "The list must have at least 2 items"),
        ({"$ref": "#/$defs/Pair"}, [1, 2, 3], "The list must have at most 2 items"),
        ({"type": "array", "minItems": 1}, [], "The list must have at least 1 item"),
    ],
)
def test_messages(schema, value, message):
    issues = checker.check(schema, value)
    assert [issue.message for issue in issues] == [message]


@pytest.mark.parametrize(
    "schema, value",
    [
        ({"type": "number", "minimum": 1}, 1),
        ({"type": "integer"}, 2.0),
        ({"$ref": "#/$defs/Colour"}, "red"),
        ({"$ref": "#/$defs/Pair"}, [1, 2]),
        ({"type": ["number", "null"]}, None),
        ({"$ref": "#/$defs/Shape"}, {"type": "Circle", "radius": 2}),
    ],
)
def test_valid_values(schema, value):
    assert checker.check(schema, value) == []
    assert checker.is_valid(schema, value)


def test_a_choice_between_types_reports_the_closest_type_only():
    """
    A circle with a negative radius is reported for the radius, not once for each
    shape the value is not.
    """
    issues = checker.check({"$ref": "#/$defs/Shape"}, {"type": "Circle", "radius": -1})
    assert issues == [SchemaIssue('"radius" must be at least 0', ("radius",))]


def test_a_property_is_named_in_the_message():
    issues = checker.check(
        {"type": "object", "properties": {"a": {"type": "number"}}}, {"a": "x"}
    )
    assert issues == [SchemaIssue('"a" must be a number', ("a",))]


def test_new_issues_ignores_what_was_already_wrong():
    old = [SchemaIssue("a", ("x",)), SchemaIssue("b", ("y",))]
    new = [SchemaIssue("a", ("x",)), SchemaIssue("c", ("z",))]
    assert new_issues(old, new) == [SchemaIssue("c", ("z",))]
    assert new_issues([], []) == []


def test_missing_file_message(tmp_path):
    model = tmp_path / "model.json"
    (tmp_path / "data.csv").write_text("a")
    assert missing_file_message("data.csv", str(model)) is None
    assert missing_file_message("other.csv", str(model)) == 'The file "other.csv" does not exist'
    assert missing_file_message(str(tmp_path / "data.csv"), str(model)) is None
    # an address, an empty path and a model that is not saved cannot be checked
    assert missing_file_message("https://example.com/a.csv", str(model)) is None
    assert missing_file_message("", str(model)) is None
    assert missing_file_message("other.csv", None) is None
    assert missing_file_message(5, str(model)) is None
