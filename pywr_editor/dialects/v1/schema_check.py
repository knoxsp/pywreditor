import json
from functools import cache
from pathlib import Path

from pywr_editor.model.schema_check import SchemaChecker, SchemaIssue, new_issues

"""
 Checks the components edited in the pywr v1 forms against the bundled pywr-v1-schema,
 with the same checker the pywr-next forms use.

 The standard schema reads a node or a parameter that does not match its core type as a
 custom one, so it only finds what is certain to be wrong; those problems stop the
 form from being saved. The strict schema also finds the problems of core components
 that the standard one lets through. It cannot tell them from a custom component or a
 feature the schema does not model, so these are only warnings.
"""

SCHEMA_DIR = Path(__file__).parents[2] / "model" / "schemas"

DEFINITIONS = {
    "node": "Node",
    "parameter": "Parameter",
    "table": "Table",
    "scenario": "Scenario",
}
""" The schema definition of each kind of component the forms edit """


@cache
def _checker(strict: bool) -> SchemaChecker:
    name = "pywr-v1-model-strict" if strict else "pywr-v1-model"
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    return SchemaChecker(schema["$defs"])


def check_component(
    kind: str, old: dict | None, new: dict
) -> tuple[list[SchemaIssue], list[SchemaIssue]]:
    """
    Checks a component after an edit.
    :param kind: The kind of component: "node", "parameter", "table" or "scenario".
    :param old: The component before the edit, None for a new component. A problem it
    already had is not reported: the edit may not have touched it.
    :param new: The component after the edit, as it is stored in the model.
    :return: The errors (what the standard schema rejects, and the edit introduced) and
    the warnings (what only the strict schema finds, and the edit introduced).
    """
    if kind in ("node", "parameter") and not new.get("type"):
        # without a type there is no schema to check the component against
        return [], []
    schema = {"$ref": f"#/$defs/{DEFINITIONS[kind]}"}
    standard, strict = _checker(False), _checker(True)
    errors = new_issues(
        standard.check(schema, old) if old else [], standard.check(schema, new)
    )
    introduced = new_issues(
        strict.check(schema, old) if old else [], strict.check(schema, new)
    )
    reported = {issue.path for issue in errors}
    warnings = [issue for issue in introduced if issue.path not in reported]
    return errors, warnings
