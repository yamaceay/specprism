"""
resolver.py  -  Convert a raw OpenAPI 3.x dict into a SpecIR.

Resolution rules (from the handoff):

  $ref '#/components/schemas/X'         -> inline target node (no $ref in IR)
  type: string/number/integer/boolean   -> NodeKind.SCALAR
  type: object  OR  properties present  -> NodeKind.OBJECT
  type: array                           -> NodeKind.ARRAY
  oneOf: [...]                          -> NodeKind.UNION, source_keyword="oneOf"
  anyOf: [{type:X},{type:null}] (2-el)  -> parent nullable=True, non-null inlined
  anyOf: [...] (general)                -> NodeKind.UNION, source_keyword="anyOf"
  allOf: [...]                          -> NodeKind.INTERSECTION, source_keyword="allOf"
  enum: [...]                           -> NodeKind.ENUM
  no type / no properties / no items   -> NodeKind.ANY

Circular $ref is broken by emitting a sentinel ANY node with a description.
Only local $ref ('#/components/schemas/...') are supported in v1.
"""

from __future__ import annotations

from typing import Any

from .ir import EndpointNode, NodeKind, ScalarType, SchemaNode, SpecIR

_SCALAR_TYPE_MAP: dict[str, ScalarType] = {
    "string": ScalarType.STRING,
    "number": ScalarType.NUMBER,
    "integer": ScalarType.INTEGER,
    "boolean": ScalarType.BOOLEAN,
    "null": ScalarType.NULL,
}

_NULL_TYPES = {"null"}

# OpenAPI fields not modeled structurally in the IR, preserved verbatim in
# the meta block so diffs can surface changes to validation rules,
# access hints, and documentation fields.
_META_FIELDS = frozenset({
    "const",
    "contains",
    "default",
    "deprecated",
    "discriminator",
    "example",
    "examples",
    "exclusiveMaximum",
    "exclusiveMinimum",
    "externalDocs",
    "multipleOf",
    "pattern",
    "patternProperties",
    "propertyNames",
    "readOnly",
    "uniqueItems",
    "writeOnly",
    "xml",
})


def _collect_meta(schema: dict[str, Any]) -> dict[str, Any] | None:
    """Return unmodeled OpenAPI fields present in *schema*, or None."""
    found = {k: v for k, v in schema.items() if k in _META_FIELDS}
    return found or None


class Resolver:
    """Resolve a raw OpenAPI 3.x dict into a :class:`SpecIR`."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw
        self._components: dict[str, Any] = (
            raw.get("components", {}).get("schemas", {})
        )
        # Guard against circular $ref: track names currently being resolved.
        self._resolving: set[str] = set()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def resolve(self) -> SpecIR:
        info = self._raw.get("info", {})
        servers = self._raw.get("servers", [{}])
        base_path = servers[0].get("url", "/") if servers else "/"

        schemas = {
            name: self._resolve_named_schema(name)
            for name in self._components
        }

        endpoints: list[EndpointNode] = []
        for path, path_item in self._raw.get("paths", {}).items():
            for method in ("get", "post", "put", "patch", "delete"):
                operation = path_item.get(method)
                if operation is None:
                    continue
                endpoints.append(self._resolve_endpoint(path, method, operation))

        endpoints.sort(key=lambda e: (e.path, e.method))

        return SpecIR(
            title=info.get("title", ""),
            version=info.get("version", ""),
            base_path=base_path,
            schemas=schemas,
            endpoints=endpoints,
        )

    # ------------------------------------------------------------------
    # Named component schema (tracks circular refs by name)
    # ------------------------------------------------------------------

    def _resolve_named_schema(self, name: str) -> SchemaNode:
        if name in self._resolving:
            # Circular reference sentinel
            return SchemaNode(
                kind=NodeKind.ANY,
                description=f"circular ref: {name}",
            )
        self._resolving.add(name)
        try:
            schema_dict = self._components.get(name, {})
            return self._resolve_schema(schema_dict)
        finally:
            self._resolving.discard(name)

    # ------------------------------------------------------------------
    # Core schema resolution
    # ------------------------------------------------------------------

    def _resolve_schema(self, schema: dict[str, Any]) -> SchemaNode:
        # Follow $ref first  -  route through _resolve_named_schema so the
        # circular-ref guard (self._resolving) applies.
        ref = schema.get("$ref")
        if ref:
            if ref.startswith("#/components/schemas/"):
                name = ref.split("/")[-1]
                return self._resolve_named_schema(name)
            # Remote / unsupported ref
            return SchemaNode(kind=NodeKind.ANY, description=f"unresolved ref: {ref}")

        schema = self._deref(schema)

        # --- nullable detection (OpenAPI 3.0 style) ---
        oa30_nullable = bool(schema.get("nullable", False))

        # --- enum ---
        if "enum" in schema:
            return SchemaNode(
                kind=NodeKind.ENUM,
                title=schema.get("title"),
                description=schema.get("description"),
                nullable=oa30_nullable,
                enum_values=schema["enum"],
                meta=_collect_meta(schema),
            )

        # --- anyOf: nullable shorthand vs. general union ---
        if "anyOf" in schema:
            return self._resolve_any_of(schema, oa30_nullable)

        # --- oneOf ---
        if "oneOf" in schema:
            variants = [self._resolve_schema(v) for v in schema["oneOf"]]
            return SchemaNode(
                kind=NodeKind.UNION,
                source_keyword="oneOf",
                title=schema.get("title"),
                description=schema.get("description"),
                nullable=oa30_nullable,
                variants=variants,
                meta=_collect_meta(schema),
            )

        # --- allOf ---
        if "allOf" in schema:
            variants = [self._resolve_schema(v) for v in schema["allOf"]]
            return SchemaNode(
                kind=NodeKind.INTERSECTION,
                source_keyword="allOf",
                title=schema.get("title"),
                description=schema.get("description"),
                nullable=oa30_nullable,
                variants=variants,
                meta=_collect_meta(schema),
            )

        raw_type = schema.get("type")

        # --- array ---
        if raw_type == "array" or "items" in schema:
            items_schema = schema.get("items")
            items_node = self._resolve_schema(items_schema) if items_schema else None
            return SchemaNode(
                kind=NodeKind.ARRAY,
                title=schema.get("title"),
                description=schema.get("description"),
                nullable=oa30_nullable,
                items=items_node,
                min_items=schema.get("minItems"),
                max_items=schema.get("maxItems"),
                meta=_collect_meta(schema),
            )

        # --- object ---
        if raw_type == "object" or "properties" in schema:
            props: dict[str, SchemaNode] | None = None
            if "properties" in schema:
                props = {
                    k: self._resolve_schema(v)
                    for k, v in schema["properties"].items()
                }

            add_props_raw = schema.get("additionalProperties")
            add_props: bool | SchemaNode | None = None
            if isinstance(add_props_raw, bool):
                add_props = add_props_raw
            elif isinstance(add_props_raw, dict):
                add_props = self._resolve_schema(add_props_raw)

            required = schema.get("required")
            if required is not None:
                required = sorted(required)

            return SchemaNode(
                kind=NodeKind.OBJECT,
                title=schema.get("title"),
                description=schema.get("description"),
                nullable=oa30_nullable,
                properties=props,
                required=required,
                additional_properties=add_props,
                meta=_collect_meta(schema),
            )

        # --- scalar ---
        if raw_type in _SCALAR_TYPE_MAP:
            return SchemaNode(
                kind=NodeKind.SCALAR,
                title=schema.get("title"),
                description=schema.get("description"),
                nullable=oa30_nullable,
                scalar_type=_SCALAR_TYPE_MAP[raw_type],
                fmt=schema.get("format"),
                minimum=schema.get("minimum"),
                maximum=schema.get("maximum"),
                min_length=schema.get("minLength"),
                max_length=schema.get("maxLength"),
                meta=_collect_meta(schema),
            )

        # --- any (no type info) ---
        return SchemaNode(
            kind=NodeKind.ANY,
            title=schema.get("title"),
            description=schema.get("description"),
            nullable=oa30_nullable,
            meta=_collect_meta(schema),
        )

    def _resolve_any_of(
        self, schema: dict[str, Any], base_nullable: bool
    ) -> SchemaNode:
        """Handle anyOf: either nullable shorthand or a general union."""
        variants_raw: list[dict[str, Any]] = schema["anyOf"]

        # OpenAPI 3.1 nullable pattern: anyOf with exactly one {type: null} entry.
        null_entries = [v for v in variants_raw if v.get("type") == "null"]
        non_null_entries = [v for v in variants_raw if v.get("type") != "null"]

        if len(null_entries) == 1 and len(non_null_entries) == 1:
            # Nullable shorthand  -  inline the non-null variant with nullable=True
            node = self._resolve_schema(non_null_entries[0])
            # Pydantic models are immutable by default; rebuild with nullable=True
            return node.model_copy(
                update={
                    "nullable": True,
                    "title": schema.get("title") or node.title,
                    "description": schema.get("description") or node.description,
                }
            )

        # General anyOf union
        variants = [self._resolve_schema(v) for v in variants_raw]
        return SchemaNode(
            kind=NodeKind.UNION,
            source_keyword="anyOf",
            title=schema.get("title"),
            description=schema.get("description"),
            nullable=base_nullable,
            variants=variants,
            meta=_collect_meta(schema),
        )

    # ------------------------------------------------------------------
    # $ref resolution
    # ------------------------------------------------------------------

    def _deref(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Follow a single local $ref, if present."""
        ref = schema.get("$ref")
        if not ref:
            return schema
        if not ref.startswith("#/components/schemas/"):
            # Remote or unsupported ref  -  treat as ANY
            return {}
        name = ref.split("/")[-1]
        return self._components.get(name, {})

    # ------------------------------------------------------------------
    # Endpoint resolution
    # ------------------------------------------------------------------

    def _resolve_endpoint(
        self, path: str, method: str, operation: dict[str, Any]
    ) -> EndpointNode:
        request_node: SchemaNode | None = None
        request_body = operation.get("requestBody", {})
        if request_body:
            rb = self._deref(request_body)
            json_schema = (
                rb.get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if json_schema is not None:
                request_node = self._resolve_schema(json_schema)
            else:
                # Non-JSON media type  -  surface as ANY with a note
                request_node = SchemaNode(
                    kind=NodeKind.ANY,
                    description="non-JSON request body (media type not resolved in v1)",
                )

        responses: dict[str, SchemaNode] = {}
        for status_code, response_raw in operation.get("responses", {}).items():
            resp = self._deref(response_raw) if isinstance(response_raw, dict) else {}
            json_schema = (
                resp.get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if json_schema is not None:
                responses[str(status_code)] = self._resolve_schema(json_schema)

        return EndpointNode(
            path=path,
            method=method,
            summary=operation.get("summary"),
            request=request_node,
            responses=responses,
        )


def resolve_file(raw: dict[str, Any]) -> SpecIR:
    """Convenience wrapper: resolve a raw OpenAPI dict into a :class:`SpecIR`."""
    return Resolver(raw).resolve()
