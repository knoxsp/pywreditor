import json
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from pywr_editor.dialects.next.validation import SCHEMA_DIR, SCHEMA_FILE

"""
 Reads the JSON Schema exported by pywr-next to describe the fields of each type of
 component. The forms of pywr-next components are generated from this description,
 so the editor follows the schema of the pywr-next version it bundles.

 The schema is generated from the Rust types with schemars:
   - a kind of component (for example "Node" or "Parameter") is a "oneOf" of object
     schemas, one per type, told apart by a "type" property with a constant value;
   - an optional property is an "anyOf" with {"type": "null"}, or a "type" list with
     "null";
   - shared definitions are in "$defs" and referenced with "$ref".
"""


@dataclass(frozen=True)
class FieldSpec:
    """The description of a property of a component, used to build its form field."""

    name: str
    """ The property name """
    label: str
    """ The label shown in the form """
    kind: str
    """ "number", "integer", "boolean", "string", "enum", "number_list", "ref"
    (a value described by a definition, see ref) or "json" (anything else) """
    required: bool = False
    """ Whether the property must be set """
    ref: str | None = None
    """ The name of the definition in "$defs" for a "ref" value """
    options: tuple[str, ...] = ()
    """ The allowed values of an "enum" """
    description: str | None = None
    """ The documentation of the property """
    default: Any = None
    """ The value pywr-next uses when the property is not set """
    minimum: float | None = None
    """ The smallest allowed number """
    schema: dict = field(default=None, compare=False, repr=False)
    """ The schema of the property, without the null alternative """


def humanise_name(name: str) -> str:
    """
    Converts a property name such as "max_flow" to a label such as "Max flow".
    :param name: The property name.
    :return: The label.
    """
    text = name.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def _first_paragraph(description: str | None) -> str | None:
    if not description:
        return None
    return description.strip().split("\n\n")[0].replace("\n", " ")


class NextSchema:
    """The bundled pywr-next schema."""

    def __init__(self, schema: dict | None = None):
        """
        :param schema: The schema dictionary. Defaults to the bundled schema.
        """
        self.schema = schema if schema is not None else _bundled_schema()
        self.defs: dict = self.schema.get("$defs", {})

    def resolve(self, schema: dict) -> dict:
        """
        Follows "$ref" to the referenced definition.
        :param schema: A schema that may be a reference.
        :return: The referenced schema, or the schema itself.
        """
        while isinstance(schema, dict) and "$ref" in schema:
            schema = self.defs[self.ref_name(schema)]
        return schema

    @staticmethod
    def ref_name(schema: dict) -> str | None:
        """
        Returns the name of the definition a schema references.
        :param schema: The schema.
        :return: The definition name or None if the schema is not a reference.
        """
        ref = schema.get("$ref") if isinstance(schema, dict) else None
        return ref.rsplit("/", 1)[-1] if isinstance(ref, str) else None

    @staticmethod
    def _tag(variant: dict) -> tuple[str, str] | None:
        # the property with a constant string value that identifies the type
        for key, prop in variant.get("properties", {}).items():
            if isinstance(prop, dict) and isinstance(prop.get("const"), str):
                return key, prop["const"]
        return None

    def _merge(self, variant: dict) -> dict:
        # a variant may have its tag next to a reference to the rest of its fields
        if "$ref" not in variant:
            return variant
        target = self.resolve(variant)
        return {
            **target,
            "properties": {
                **variant.get("properties", {}),
                **target.get("properties", {}),
            },
            "required": list(
                dict.fromkeys(variant.get("required", []) + target.get("required", []))
            ),
        }

    def variants(self, definition: str) -> dict[str, dict]:
        """
        Returns the types of a kind of component.
        :param definition: The definition of the kind, such as "Node".
        :return: The object schema of each type, by type name, in schema order.
        """
        schema = self.resolve(self.defs[definition])
        variants = {}
        for variant in schema.get("oneOf", schema.get("anyOf", [])):
            merged = self._merge(variant)
            tag = self._tag(variant) or self._tag(merged)
            if tag is not None:
                variants[tag[1]] = merged
        return variants

    def tag_key(self, definition: str) -> str:
        """
        Returns the property that identifies the type of a component, which is
        "type" for most kinds and "format" for tables.
        :param definition: The definition of the kind, such as "DataTable".
        :return: The property name.
        """
        for variant in self.variants(definition).values():
            tag = self._tag(variant)
            if tag is not None:
                return tag[0]
        return "type"

    def types(self, definition: str) -> list[str]:
        """
        Returns the names of the types of a kind of component.
        :param definition: The definition of the kind, such as "Parameter".
        :return: The type names, in schema order.
        """
        return list(self.variants(definition))

    def description(self, definition: str, type_name: str) -> str | None:
        """
        Returns the documentation of a type of component.
        :param definition: The definition of the kind, such as "Node".
        :param type_name: The type, such as "Reservoir".
        :return: The first paragraph of the documentation, if any.
        """
        return _first_paragraph(self.variants(definition)[type_name].get("description"))

    def fields(
        self,
        definition: str,
        type_name: str,
        skip: tuple[str, ...] = ("meta",),
    ) -> list[FieldSpec]:
        """
        Describes the properties of a type of component.
        :param definition: The definition of the kind, such as "Node".
        :param type_name: The type, such as "Reservoir".
        :param skip: The properties that are not edited with a generated field. The
        "meta" (name, comment...) is edited by the dialog itself, and the property
        with the type is always left out.
        :return: The field descriptions, the required ones first.
        """
        skip = (*skip, self.tag_key(definition))
        return self.object_fields(self.variants(definition)[type_name], skip)

    def object_fields(
        self, schema: dict, skip: tuple[str, ...] = ()
    ) -> list[FieldSpec]:
        """
        Describes the properties of an object schema.
        :param schema: The object schema.
        :param skip: The properties to leave out.
        :return: The field descriptions, the required ones first.
        """
        schema = self.resolve(schema)
        required = set(schema.get("required", []))
        specs = [
            self.field_spec(name, prop, name in required)
            for name, prop in schema.get("properties", {}).items()
            if name not in skip
        ]
        return sorted(specs, key=lambda spec: not spec.required)

    @staticmethod
    def _without_null(schema: dict) -> tuple[dict, bool]:
        # returns the schema without its null alternative, and whether it had one
        for key in ("anyOf", "oneOf"):
            options = schema.get(key)
            if isinstance(options, list):
                not_null = [o for o in options if o != {"type": "null"}]
                if len(not_null) == 1 and len(not_null) < len(options):
                    merged = {k: v for k, v in schema.items() if k != key}
                    return {**not_null[0], **merged}, True
        types = schema.get("type")
        if isinstance(types, list) and "null" in types:
            others = [t for t in types if t != "null"]
            return {**schema, "type": others[0] if len(others) == 1 else others}, True
        return schema, False

    def _enum_options(self, schema: dict) -> tuple[str, ...] | None:
        # string enums are a list of values, or a "oneOf" of constant strings
        if isinstance(schema.get("enum"), list) and all(
            isinstance(v, str) for v in schema["enum"]
        ):
            return tuple(schema["enum"])
        options = schema.get("oneOf")
        if isinstance(options, list) and options:
            values = []
            for option in options:
                if option.get("type") == "string" and isinstance(
                    option.get("const"), str
                ):
                    values.append(option["const"])
                elif isinstance(option.get("enum"), list):
                    values += [v for v in option["enum"] if isinstance(v, str)]
                else:
                    return None
            return tuple(values)
        return None

    def field_spec(self, name: str, schema: dict, required: bool) -> FieldSpec:
        """
        Describes a property.
        :param name: The property name.
        :param schema: The property schema.
        :param required: Whether the property is required.
        :return: The field description.
        """
        schema, nullable = self._without_null(schema)
        common = dict(
            name=name,
            label=humanise_name(name),
            required=required and not nullable,
            description=_first_paragraph(schema.get("description")),
            default=schema.get("default"),
            schema=schema,
        )

        ref = self.ref_name(schema)
        target = self.resolve(schema)
        options = self._enum_options(target)
        if options is not None:
            return FieldSpec(kind="enum", options=options, ref=ref, **common)
        if ref is not None:
            return FieldSpec(kind="ref", ref=ref, **common)

        json_type = schema.get("type")
        if json_type in ("number", "integer"):
            return FieldSpec(
                kind=json_type,
                minimum=schema.get("minimum", schema.get("exclusiveMinimum")),
                **common,
            )
        if json_type == "boolean":
            return FieldSpec(kind="boolean", **common)
        if json_type == "string":
            return FieldSpec(kind="string", **common)
        if json_type == "array":
            items = schema.get("items")
            items = self.resolve(items) if isinstance(items, dict) else {}
            if (
                items.get("type") in ("number", "integer")
                and "prefixItems" not in schema
            ):
                return FieldSpec(kind="number_list", **common)
        return FieldSpec(kind="json", **common)


@cache
def _bundled_schema() -> dict:
    return json.loads((SCHEMA_DIR / SCHEMA_FILE).read_text())


@cache
def bundled_schema() -> NextSchema:
    """
    Returns the bundled pywr-next schema.
    :return: The schema.
    """
    return NextSchema()
