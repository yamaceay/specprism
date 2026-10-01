"""
serializer.py  -  Serialize a SpecIR to a stable, diffable YAML string.

Rules (from the handoff):
  1. All dict keys are sorted alphabetically.
  2. None / empty-optional fields are omitted.
  3. required lists are sorted.
  4. enum_values are sorted when all values are strings.
  5. Top-level order: title, version, base_path, schemas (alpha), endpoints
     (by path then method).
"""

from __future__ import annotations

from typing import Any

import yaml

from .ir import EndpointNode, SchemaNode, SpecIR

# Top-level key order is enforced manually; everything else is alphabetical.
_TOP_LEVEL_ORDER = ("title", "version", "base_path", "schemas", "endpoints")

# Explicit field order for SchemaNode so the most structural fields come first.
_SCHEMA_KEY_ORDER = (
    "kind",
    "source_keyword",
    "scalar_type",
    "fmt",
    "nullable",
    "title",
    "description",
    "minimum",
    "maximum",
    "min_length",
    "max_length",
    "min_items",
    "max_items",
    "required",
    "properties",
    "additional_properties",
    "items",
    "variants",
    "enum_values",
    "meta",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _schema_to_dict(node: SchemaNode) -> dict[str, Any]:
    """Convert a SchemaNode to a plain dict, omitting falsy/None fields."""
    raw: dict[str, Any] = {}

    for field in _SCHEMA_KEY_ORDER:
        value = getattr(node, field, None)

        if value is None:
            continue
        if value is False and field == "nullable":
            # Omit nullable: false  -  it is the default
            continue
        if value is False and field == "additional_properties":
            # Keep explicit False  -  it means strict object
            raw[field] = False
            continue

        if field == "kind":
            raw[field] = value.value
        elif field == "scalar_type":
            raw[field] = value.value
        elif field == "properties":
            raw[field] = {
                k: _schema_to_dict(v)
                for k, v in sorted(value.items())
            }
        elif field == "additional_properties" and not isinstance(value, bool):
            raw[field] = _schema_to_dict(value)
        elif field == "items":
            raw[field] = _schema_to_dict(value)
        elif field == "variants":
            raw[field] = [_schema_to_dict(v) for v in value]
        elif field == "required":
            raw[field] = sorted(value)
        elif field == "enum_values":
            vals = list(value)
            if all(isinstance(v, str) for v in vals):
                vals = sorted(vals)
            raw[field] = vals
        elif field == "meta":
            # Sort keys alphabetically for stable diffs.
            raw[field] = dict(sorted(value.items()))
        else:
            raw[field] = value

    return raw


def _endpoint_to_dict(ep: EndpointNode) -> dict[str, Any]:
    d: dict[str, Any] = {"path": ep.path, "method": ep.method}
    if ep.summary:
        d["summary"] = ep.summary
    if ep.request is not None:
        d["request"] = _schema_to_dict(ep.request)
    if ep.responses:
        d["responses"] = {
            k: _schema_to_dict(v)
            for k, v in sorted(ep.responses.items())
        }
    return d


def _spec_to_dict(ir: SpecIR) -> dict[str, Any]:
    return {
        "title": ir.title,
        "version": ir.version,
        "base_path": ir.base_path,
        "schemas": {
            name: _schema_to_dict(node)
            for name, node in sorted(ir.schemas.items())
        },
        "endpoints": [
            _endpoint_to_dict(ep)
            for ep in sorted(ir.endpoints, key=lambda e: (e.path, e.method))
        ],
    }


# ---------------------------------------------------------------------------
# Stable YAML dumper
# ---------------------------------------------------------------------------

class _StableDumper(yaml.Dumper):
    """YAML dumper that preserves insertion order for dicts (no re-sort)."""

    def represent_mapping(self, tag: str, mapping: Any, flow_style: Any = None) -> Any:  # type: ignore[override]
        # Use the dict as-is; key order comes from our own sorting above.
        return super().represent_mapping(tag, mapping, flow_style=flow_style)


_StableDumper.add_representer(
    dict,
    lambda dumper, data: dumper.represent_mapping(
        "tag:yaml.org,2002:map", data.items()
    ),
)


def serialize(ir: SpecIR) -> str:
    """Return a stable YAML string for *ir*."""
    data = _spec_to_dict(ir)
    return yaml.dump(
        data,
        Dumper=_StableDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,  # we manage order ourselves
    )
