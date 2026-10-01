"""
ir.py  -  Pydantic models for the specprism Intermediate Representation (IR).

Every OpenAPI schema node maps to exactly one SchemaNode.  The tree is
serialized to YAML in a deterministic key order so that diffs are meaningful.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel


class ScalarType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    NULL = "null"


class NodeKind(str, Enum):
    SCALAR = "scalar"          # string, number, integer, boolean, null
    OBJECT = "object"          # properties + optional additionalProperties
    ARRAY = "array"            # items
    UNION = "union"            # oneOf / anyOf  (noted in source_keyword)
    INTERSECTION = "intersection"  # allOf
    ENUM = "enum"              # enum values list
    ANY = "any"                # no type constraint at all


class SchemaNode(BaseModel):
    kind: NodeKind

    # Common metadata
    title: Optional[str] = None
    description: Optional[str] = None
    nullable: bool = False  # anyOf: [{...}, {type: null}] pattern

    # SCALAR
    scalar_type: Optional[ScalarType] = None
    fmt: Optional[str] = None        # format field
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None

    # OBJECT
    properties: Optional[dict[str, "SchemaNode"]] = None
    required: Optional[list[str]] = None
    additional_properties: Optional[Union[bool, "SchemaNode"]] = None

    # ARRAY
    items: Optional["SchemaNode"] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None

    # UNION / INTERSECTION
    source_keyword: Optional[str] = None       # "oneOf" | "anyOf" | "allOf"
    variants: Optional[list["SchemaNode"]] = None

    # ENUM
    enum_values: Optional[list[Any]] = None

    # OpenAPI fields not fully modeled in the IR.
    # Captured as-is so diffs surface changes to pattern, default,
    # readOnly, deprecated, discriminator, and similar constraints.
    # Keys are sorted alphabetically during serialization.
    meta: Optional[dict[str, Any]] = None


class EndpointNode(BaseModel):
    path: str
    method: str                               # get | post | put | patch | delete
    summary: Optional[str] = None
    request: Optional[SchemaNode] = None      # resolved request body schema
    responses: dict[str, SchemaNode]          # status_code -> schema


class SpecIR(BaseModel):
    title: str
    version: str
    base_path: str                            # servers[0].url
    schemas: dict[str, SchemaNode]            # resolved component schemas
    endpoints: list[EndpointNode]
