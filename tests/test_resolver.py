"""
test_resolver.py  -  Unit tests for the Resolver.

All fixtures are inline dicts; no external spec files required for these tests.
"""

from __future__ import annotations

import pytest

from openapi_comparator.ir import NodeKind, ScalarType
from openapi_comparator.resolver import resolve_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_spec(schemas: dict, paths: dict | None = None) -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1.0.0"},
        "servers": [{"url": "/"}],
        "components": {"schemas": schemas},
        "paths": paths or {},
    }


# ---------------------------------------------------------------------------
# Scalar types
# ---------------------------------------------------------------------------

def test_scalar_string():
    spec = _minimal_spec({"Name": {"type": "string"}})
    ir = resolve_file(spec)
    node = ir.schemas["Name"]
    assert node.kind == NodeKind.SCALAR
    assert node.scalar_type == ScalarType.STRING


def test_scalar_number_with_bounds():
    spec = _minimal_spec({
        "Score": {"type": "number", "minimum": 0.0, "maximum": 1.0}
    })
    ir = resolve_file(spec)
    node = ir.schemas["Score"]
    assert node.kind == NodeKind.SCALAR
    assert node.scalar_type == ScalarType.NUMBER
    assert node.minimum == 0.0
    assert node.maximum == 1.0


# ---------------------------------------------------------------------------
# Nullable patterns
# ---------------------------------------------------------------------------

def test_nullable_oa30():
    """OpenAPI 3.0 nullable: true on a scalar."""
    spec = _minimal_spec({"MaybeStr": {"type": "string", "nullable": True}})
    ir = resolve_file(spec)
    node = ir.schemas["MaybeStr"]
    assert node.nullable is True
    assert node.scalar_type == ScalarType.STRING


def test_nullable_oa31_anyof_pattern():
    """OpenAPI 3.1 anyOf [{type:number},{type:null}] -> single nullable scalar."""
    spec = _minimal_spec({
        "MaybeNum": {
            "anyOf": [{"type": "number"}, {"type": "null"}]
        }
    })
    ir = resolve_file(spec)
    node = ir.schemas["MaybeNum"]
    assert node.nullable is True
    assert node.kind == NodeKind.SCALAR
    assert node.scalar_type == ScalarType.NUMBER


# ---------------------------------------------------------------------------
# Object
# ---------------------------------------------------------------------------

def test_object_with_properties():
    spec = _minimal_spec({
        "Person": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
    })
    ir = resolve_file(spec)
    node = ir.schemas["Person"]
    assert node.kind == NodeKind.OBJECT
    assert "name" in node.properties
    assert "age" in node.properties
    assert node.required == ["name"]


def test_additional_properties_bool():
    spec = _minimal_spec({
        "OpenObj": {"type": "object", "additionalProperties": True}
    })
    ir = resolve_file(spec)
    node = ir.schemas["OpenObj"]
    assert node.additional_properties is True


def test_additional_properties_schema():
    spec = _minimal_spec({
        "MapOfStr": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        }
    })
    ir = resolve_file(spec)
    node = ir.schemas["MapOfStr"]
    assert node.additional_properties is not None
    assert not isinstance(node.additional_properties, bool)
    assert node.additional_properties.scalar_type == ScalarType.STRING


# ---------------------------------------------------------------------------
# Array
# ---------------------------------------------------------------------------

def test_array_with_items():
    spec = _minimal_spec({
        "Names": {"type": "array", "items": {"type": "string"}}
    })
    ir = resolve_file(spec)
    node = ir.schemas["Names"]
    assert node.kind == NodeKind.ARRAY
    assert node.items.scalar_type == ScalarType.STRING


def test_array_min_max_items():
    spec = _minimal_spec({
        "Pair": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        }
    })
    ir = resolve_file(spec)
    node = ir.schemas["Pair"]
    assert node.min_items == 2
    assert node.max_items == 2


# ---------------------------------------------------------------------------
# oneOf / anyOf / allOf
# ---------------------------------------------------------------------------

def test_one_of():
    spec = _minimal_spec({
        "Request": {
            "oneOf": [
                {"type": "object", "properties": {"rows": {"type": "array", "items": {}}}},
                {"type": "object", "properties": {"columns": {"type": "object"}}},
            ]
        }
    })
    ir = resolve_file(spec)
    node = ir.schemas["Request"]
    assert node.kind == NodeKind.UNION
    assert node.source_keyword == "oneOf"
    assert len(node.variants) == 2


def test_any_of_general():
    """anyOf with more than one non-null entry -> UNION."""
    spec = _minimal_spec({
        "Multi": {
            "anyOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
            ]
        }
    })
    ir = resolve_file(spec)
    node = ir.schemas["Multi"]
    assert node.kind == NodeKind.UNION
    assert node.source_keyword == "anyOf"
    assert len(node.variants) == 3


def test_all_of():
    spec = _minimal_spec({
        "Combined": {
            "allOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "object", "properties": {"b": {"type": "integer"}}},
            ]
        }
    })
    ir = resolve_file(spec)
    node = ir.schemas["Combined"]
    assert node.kind == NodeKind.INTERSECTION
    assert node.source_keyword == "allOf"


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------

def test_enum():
    spec = _minimal_spec({
        "Color": {"enum": ["red", "green", "blue"]}
    })
    ir = resolve_file(spec)
    node = ir.schemas["Color"]
    assert node.kind == NodeKind.ENUM
    assert set(node.enum_values) == {"red", "green", "blue"}


# ---------------------------------------------------------------------------
# $ref resolution
# ---------------------------------------------------------------------------

def test_ref_resolution():
    spec = _minimal_spec({
        "Name": {"type": "string"},
        "Person": {
            "type": "object",
            "properties": {
                "name": {"$ref": "#/components/schemas/Name"}
            },
        },
    })
    ir = resolve_file(spec)
    node = ir.schemas["Person"]
    assert node.properties["name"].kind == NodeKind.SCALAR
    assert node.properties["name"].scalar_type == ScalarType.STRING


def test_circular_ref_sentinel():
    """A circular $ref must not crash; it emits an ANY sentinel."""
    spec = _minimal_spec({
        "Node": {
            "type": "object",
            "properties": {
                "child": {"$ref": "#/components/schemas/Node"}
            },
        }
    })
    ir = resolve_file(spec)
    child = ir.schemas["Node"].properties["child"]
    assert child.kind == NodeKind.ANY
    assert "circular" in (child.description or "").lower()


# ---------------------------------------------------------------------------
# ANY fallback
# ---------------------------------------------------------------------------

def test_any_fallback():
    spec = _minimal_spec({"Anything": {}})
    ir = resolve_file(spec)
    assert ir.schemas["Anything"].kind == NodeKind.ANY


# ---------------------------------------------------------------------------
# Endpoint resolution
# ---------------------------------------------------------------------------

def test_endpoint_resolved():
    spec = _minimal_spec(
        schemas={},
        paths={
            "/items": {
                "post": {
                    "summary": "Create an item",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"}
                            }
                        }
                    },
                    "responses": {
                        "201": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        }
                    },
                }
            }
        },
    )
    ir = resolve_file(spec)
    assert len(ir.endpoints) == 1
    ep = ir.endpoints[0]
    assert ep.path == "/items"
    assert ep.method == "post"
    assert ep.request is not None
    assert ep.request.kind == NodeKind.OBJECT
    assert "201" in ep.responses


# ---------------------------------------------------------------------------
# meta block
# ---------------------------------------------------------------------------

def test_meta_captures_pattern_and_default():
    spec = _minimal_spec({
        "Username": {
            "type": "string",
            "pattern": "^[a-z0-9_]+$",
            "default": "guest",
            "minLength": 3,
        }
    })
    ir = resolve_file(spec)
    node = ir.schemas["Username"]
    assert node.kind == NodeKind.SCALAR
    assert node.min_length == 3          # modeled field
    assert node.meta is not None
    assert node.meta["pattern"] == "^[a-z0-9_]+$"
    assert node.meta["default"] == "guest"


def test_meta_captures_readonly_deprecated():
    spec = _minimal_spec({
        "LegacyId": {
            "type": "integer",
            "readOnly": True,
            "deprecated": True,
        }
    })
    ir = resolve_file(spec)
    node = ir.schemas["LegacyId"]
    assert node.meta is not None
    assert node.meta["readOnly"] is True
    assert node.meta["deprecated"] is True


def test_meta_captures_discriminator():
    spec = _minimal_spec({
        "Shape": {
            "oneOf": [
                {"type": "object", "properties": {"radius": {"type": "number"}}},
                {"type": "object", "properties": {"side": {"type": "number"}}},
            ],
            "discriminator": {"propertyName": "kind"},
        }
    })
    ir = resolve_file(spec)
    node = ir.schemas["Shape"]
    assert node.meta is not None
    assert node.meta["discriminator"] == {"propertyName": "kind"}


def test_meta_absent_when_no_extra_fields():
    spec = _minimal_spec({"Count": {"type": "integer"}})
    ir = resolve_file(spec)
    assert ir.schemas["Count"].meta is None


def test_meta_serialized_sorted():
    spec = _minimal_spec({
        "Token": {
            "type": "string",
            "writeOnly": True,
            "default": "",
            "pattern": "^[A-Z]+$",
        }
    })
    ir = resolve_file(spec)
    from openapi_comparator.serializer import _schema_to_dict
    d = _schema_to_dict(ir.schemas["Token"])
    assert list(d["meta"].keys()) == sorted(d["meta"].keys())
