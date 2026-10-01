"""
test_differ.py  -  Unit tests for the differ and know-how annotation.
"""

from __future__ import annotations

from openapi_comparator.differ import diff_yaml
from openapi_comparator.knowhow import KnowhowFile, annotate_yaml
from openapi_comparator.resolver import resolve_file
from openapi_comparator.serializer import serialize


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(title: str, version: str, schemas: dict, paths: dict | None = None) -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": title, "version": version},
        "servers": [{"url": "/"}],
        "components": {"schemas": schemas},
        "paths": paths or {},
    }


def _diff_specs(spec_a: dict, spec_b: dict) -> str:
    yaml_a = serialize(resolve_file(spec_a))
    yaml_b = serialize(resolve_file(spec_b))
    return diff_yaml(yaml_a, yaml_b, label_a="v1", label_b="v2")


# ---------------------------------------------------------------------------
# Basic diff behavior
# ---------------------------------------------------------------------------

def test_identical_specs_no_diff():
    spec = _spec("API", "1.0", {"Name": {"type": "string"}})
    result = _diff_specs(spec, spec)
    assert result == ""


def test_added_property_appears_in_diff():
    v1 = _spec("API", "1.0", {
        "Item": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
        }
    })
    v2 = _spec("API", "2.0", {
        "Item": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
            },
        }
    })
    result = _diff_specs(v1, v2)
    assert "+      name:" in result


def test_removed_property_appears_in_diff():
    v1 = _spec("API", "1.0", {
        "Item": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "legacy": {"type": "string"},
            },
        }
    })
    v2 = _spec("API", "2.0", {
        "Item": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
        }
    })
    result = _diff_specs(v1, v2)
    assert "-      legacy:" in result


def test_version_change_appears_in_diff():
    v1 = _spec("API", "1.0", {})
    v2 = _spec("API", "2.0", {})
    result = _diff_specs(v1, v2)
    assert "-version: '1.0'" in result or "-version: 1.0" in result
    assert "+version: '2.0'" in result or "+version: 2.0" in result


def test_diff_labels():
    spec = _spec("API", "1.0", {})
    yaml_a = serialize(resolve_file(spec))
    yaml_b = serialize(resolve_file(spec))
    result = diff_yaml(yaml_a, yaml_b, label_a="old", label_b="new")
    # Identical -> empty
    assert result == ""

    # Mutate yaml_b
    yaml_b_modified = yaml_b.replace("1.0", "2.0")
    result = diff_yaml(yaml_a, yaml_b_modified, label_a="old", label_b="new")
    assert "--- old" in result
    assert "+++ new" in result


def test_nullable_added_appears_in_diff():
    v1 = _spec("API", "1.0", {
        "Score": {"type": "number"}
    })
    v2 = _spec("API", "2.0", {
        "Score": {"type": "number", "nullable": True}
    })
    result = _diff_specs(v1, v2)
    assert "+    nullable: true" in result


def test_union_added_appears_in_diff():
    """Upgrading a plain object to a oneOf union shows in the diff."""
    v1 = _spec("API", "1.0", {
        "Request": {
            "type": "object",
            "properties": {"rows": {"type": "array", "items": {}}},
        }
    })
    v2 = _spec("API", "2.0", {
        "Request": {
            "oneOf": [
                {"type": "object", "properties": {"rows": {"type": "array", "items": {}}}},
                {"type": "object", "properties": {"columns": {"type": "object"}}},
            ]
        }
    })
    result = _diff_specs(v1, v2)
    assert "+kind: union" in result or "kind: union" in result


# ---------------------------------------------------------------------------
# Know-how annotation
# ---------------------------------------------------------------------------

def test_knowhow_note_injected():
    kh_yaml = """
version: 1
annotations:
  - path: schemas.Color
    note: Enum of all color strings.
    sdk_equivalent: Color.value
"""
    spec = _spec("API", "1.0", {"Color": {"enum": ["red", "green", "blue"]}})
    ir_yaml = serialize(resolve_file(spec))

    kh = KnowhowFile.from_yaml(kh_yaml)
    annotated = annotate_yaml(ir_yaml, kh)

    assert "# note: Enum of all color strings." in annotated
    assert "# sdk: Color.value" in annotated


def test_knowhow_missing_path_skipped():
    """Annotations for paths that do not exist in the YAML are silently skipped."""
    kh_yaml = """
version: 1
annotations:
  - path: schemas.DoesNotExist
    note: Should be ignored.
"""
    spec = _spec("API", "1.0", {"Color": {"enum": ["red"]}})
    ir_yaml = serialize(resolve_file(spec))

    kh = KnowhowFile.from_yaml(kh_yaml)
    annotated = annotate_yaml(ir_yaml, kh)
    assert "Should be ignored" not in annotated


def test_knowhow_empty_no_change():
    kh = KnowhowFile()
    spec = _spec("API", "1.0", {"A": {"type": "string"}})
    ir_yaml = serialize(resolve_file(spec))
    assert annotate_yaml(ir_yaml, kh) == ir_yaml
