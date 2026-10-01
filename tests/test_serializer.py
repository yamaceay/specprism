"""
test_serializer.py  -  Unit tests for the serializer.

Covers deterministic key order, field omission, and stable round-trip.
"""

from __future__ import annotations

import yaml

from openapi_comparator.ir import EndpointNode, NodeKind, SchemaNode, SpecIR
from openapi_comparator.resolver import resolve_file
from openapi_comparator.serializer import serialize


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_ir(**kwargs) -> SpecIR:
    defaults = dict(
        title="Test",
        version="1.0",
        base_path="/",
        schemas={},
        endpoints=[],
    )
    defaults.update(kwargs)
    return SpecIR(**defaults)


def _parse_yaml(text: str) -> dict:
    return yaml.safe_load(text)


# ---------------------------------------------------------------------------
# Top-level key order
# ---------------------------------------------------------------------------

def test_top_level_key_order():
    ir = _minimal_ir()
    text = serialize(ir)
    data = _parse_yaml(text)
    keys = list(data.keys())
    assert keys == ["title", "version", "base_path", "schemas", "endpoints"]


# ---------------------------------------------------------------------------
# None / empty fields omitted
# ---------------------------------------------------------------------------

def test_none_fields_omitted():
    node = SchemaNode(kind=NodeKind.SCALAR)
    # scalar_type not set -> should not appear
    from openapi_comparator.serializer import _schema_to_dict
    d = _schema_to_dict(node)
    assert "scalar_type" not in d
    assert "nullable" not in d  # False by default -> omitted


def test_nullable_true_present():
    node = SchemaNode(kind=NodeKind.SCALAR, nullable=True)
    from openapi_comparator.serializer import _schema_to_dict
    d = _schema_to_dict(node)
    assert d["nullable"] is True


# ---------------------------------------------------------------------------
# Schemas sorted alphabetically
# ---------------------------------------------------------------------------

def test_schemas_sorted():
    ir = _minimal_ir(schemas={
        "Zebra": SchemaNode(kind=NodeKind.ANY),
        "Apple": SchemaNode(kind=NodeKind.ANY),
        "Mango": SchemaNode(kind=NodeKind.ANY),
    })
    data = _parse_yaml(serialize(ir))
    assert list(data["schemas"].keys()) == ["Apple", "Mango", "Zebra"]


# ---------------------------------------------------------------------------
# Properties sorted alphabetically
# ---------------------------------------------------------------------------

def test_properties_sorted():
    node = SchemaNode(
        kind=NodeKind.OBJECT,
        properties={
            "zzz": SchemaNode(kind=NodeKind.ANY),
            "aaa": SchemaNode(kind=NodeKind.ANY),
        },
    )
    from openapi_comparator.serializer import _schema_to_dict
    d = _schema_to_dict(node)
    assert list(d["properties"].keys()) == ["aaa", "zzz"]


# ---------------------------------------------------------------------------
# Enum values sorted for string enums
# ---------------------------------------------------------------------------

def test_enum_values_sorted_strings():
    node = SchemaNode(kind=NodeKind.ENUM, enum_values=["c", "a", "b"])
    from openapi_comparator.serializer import _schema_to_dict
    d = _schema_to_dict(node)
    assert d["enum_values"] == ["a", "b", "c"]


def test_enum_values_not_sorted_mixed():
    """Mixed-type enum values must NOT be sorted (would raise TypeError)."""
    node = SchemaNode(kind=NodeKind.ENUM, enum_values=[3, "a", 1])
    from openapi_comparator.serializer import _schema_to_dict
    d = _schema_to_dict(node)
    # Order preserved as-is
    assert d["enum_values"] == [3, "a", 1]


# ---------------------------------------------------------------------------
# Endpoints sorted by path then method
# ---------------------------------------------------------------------------

def test_endpoints_sorted():
    ir = _minimal_ir(endpoints=[
        EndpointNode(path="/z", method="get", responses={}),
        EndpointNode(path="/a", method="post", responses={}),
        EndpointNode(path="/a", method="get", responses={}),
    ])
    data = _parse_yaml(serialize(ir))
    eps = data["endpoints"]
    assert [(e["path"], e["method"]) for e in eps] == [
        ("/a", "get"),
        ("/a", "post"),
        ("/z", "get"),
    ]


# ---------------------------------------------------------------------------
# Stable round-trip
# ---------------------------------------------------------------------------

def test_stable_round_trip():
    """parse -> serialize -> parse -> serialize must be identical."""
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "RT Test", "version": "2.0"},
        "servers": [{"url": "/api"}],
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "nullable": True,
                        },
                    },
                    "required": ["id", "name"],
                    "additionalProperties": False,
                }
            }
        },
        "paths": {},
    }
    ir1 = resolve_file(spec)
    yaml1 = serialize(ir1)

    ir2 = resolve_file(spec)
    yaml2 = serialize(ir2)

    assert yaml1 == yaml2


# ---------------------------------------------------------------------------
# additional_properties: false is preserved
# ---------------------------------------------------------------------------

def test_additional_properties_false_preserved():
    node = SchemaNode(kind=NodeKind.OBJECT, additional_properties=False)
    from openapi_comparator.serializer import _schema_to_dict
    d = _schema_to_dict(node)
    assert d.get("additional_properties") is False
