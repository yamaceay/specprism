"""
knowhow.py  -  Know-how annotation file models and YAML merge logic.

A know-how file annotates IR paths with semantic notes and SDK equivalences.
It does NOT mutate the IR; instead it injects ``# note:`` comments into the
serialized YAML before diffing.

Path DSL (v1)
-------------
Paths use dot notation with optional bracket indexing:

    schemas.Foo                                    -> top-level schema
    schemas.Foo.properties.bar                     -> property of an object
    schemas.Foo.variants[0]                        -> first variant of a union
    schemas.Foo.variants[0].properties.columns     -> property inside a variant
    endpoints./payments.post.request               -> endpoint request schema
    endpoints./payments.post.responses.201         -> endpoint response schema
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

import yaml
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AnnotationKind(str, Enum):
    NOTE = "note"
    KNOWN_CHANGE = "known_change"
    EQUIVALENCE = "equivalence"
    SUPPRESS = "suppress"


class Annotation(BaseModel):
    kind: AnnotationKind = AnnotationKind.NOTE

    # --- note / known_change / suppress ---
    path: Optional[str] = None          # IR path (dot notation)
    note: Optional[str] = None          # free-text explanation
    sdk_equivalent: Optional[str] = None

    # --- known_change ---
    from_version: Optional[str] = None
    to_version: Optional[str] = None
    reason: Optional[str] = None        # why the change happened

    # --- equivalence ---
    path_a: Optional[str] = None        # path in spec A
    path_b: Optional[str] = None        # path in spec B

    # --- suppress ---
    # uses path + reason


class KnowhowFile(BaseModel):
    version: int = 2
    annotations: list[Annotation] = []

    @classmethod
    def from_yaml(cls, text: str) -> "KnowhowFile":
        data = yaml.safe_load(text) or {}
        return cls.model_validate(data)

    @classmethod
    def from_file(cls, path: str) -> "KnowhowFile":
        with open(path, encoding="utf-8") as fh:
            return cls.from_yaml(fh.read())


# ---------------------------------------------------------------------------
# Path -> line-number resolver
# ---------------------------------------------------------------------------

# Regex to split a path segment that may include a bracket index, e.g. variants[0]
_SEGMENT_RE = re.compile(r"^([^\[]+)(?:\[(\d+)\])?$")


def _path_to_yaml_key_sequence(path: str) -> list[str | int]:
    """Convert a DSL path string into a list of keys/indices."""
    parts: list[str | int] = []
    for segment in path.split("."):
        m = _SEGMENT_RE.match(segment)
        if m:
            parts.append(m.group(1))
            if m.group(2) is not None:
                parts.append(int(m.group(2)))
        else:
            parts.append(segment)
    return parts


def _find_line_for_path(yaml_lines: list[str], path: str) -> int | None:
    """
    Return the 0-based line index in *yaml_lines* that best matches *path*.

    This is a best-effort heuristic: it walks the indented YAML looking for
    each key in the path sequence.  Returns None if the path cannot be found.
    """
    keys = _path_to_yaml_key_sequence(path)
    line_idx = 0
    current_indent = -1

    for key in keys:
        if isinstance(key, int):
            # Advance past *key* number of list items (lines starting with "- ")
            count = 0
            while line_idx < len(yaml_lines):
                stripped = yaml_lines[line_idx].lstrip()
                if stripped.startswith("- "):
                    if count == key:
                        break
                    count += 1
                line_idx += 1
            continue

        # String key: find "  key:" at the correct depth
        found = False
        while line_idx < len(yaml_lines):
            line = yaml_lines[line_idx]
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if stripped.startswith(f"{key}:") and indent > current_indent:
                current_indent = indent
                found = True
                break
            line_idx += 1

        if not found:
            return None

    return line_idx


# ---------------------------------------------------------------------------
# Merge: inject # note: comments into serialized YAML
# ---------------------------------------------------------------------------

def annotate_yaml(yaml_text: str, knowhow: KnowhowFile) -> str:
    """
    Return a copy of *yaml_text* with comment lines inserted for each annotation.

    - note        -> ``# note: ...`` before the path
    - known_change -> ``# ✓ known(<from> → <to>): <reason>`` before the path
    - equivalence  -> ``# ≡ <path_a> ↔ <path_b>: <note>`` before path_a and path_b
    - suppress     -> removes the matched block (not yet implemented; adds tombstone)

    Annotations that cannot be resolved to a line are silently skipped.
    """
    if not knowhow.annotations:
        return yaml_text

    lines = yaml_text.splitlines(keepends=True)
    insertions: dict[int, list[str]] = {}

    def _insert(line_idx: int, comment_lines: list[str]) -> None:
        insertions.setdefault(line_idx, []).extend(comment_lines)

    def _prefix(line_idx: int) -> str:
        line = lines[line_idx]
        indent = len(line) - len(line.lstrip())
        return " " * indent

    for ann in knowhow.annotations:
        if ann.kind == AnnotationKind.NOTE:
            if ann.path is None:
                continue
            idx = _find_line_for_path(lines, ann.path)
            if idx is None:
                continue
            p = _prefix(idx)
            comments = []
            if ann.note:
                comments.append(f"{p}# note: {ann.note.strip()}\n")
            if ann.sdk_equivalent:
                comments.append(f"{p}# sdk: {ann.sdk_equivalent}\n")
            if comments:
                _insert(idx, comments)

        elif ann.kind == AnnotationKind.KNOWN_CHANGE:
            if ann.path is None:
                continue
            idx = _find_line_for_path(lines, ann.path)
            if idx is None:
                continue
            p = _prefix(idx)
            ver = ""
            if ann.from_version and ann.to_version:
                ver = f" ({ann.from_version} → {ann.to_version})"
            reason = (ann.reason or "").strip()
            _insert(idx, [f"{p}# ✓ known{ver}: {reason}\n"])

        elif ann.kind == AnnotationKind.EQUIVALENCE:
            label = (ann.note or "").strip()
            for path in filter(None, [ann.path_a, ann.path_b]):
                idx = _find_line_for_path(lines, path)
                if idx is None:
                    continue
                other = ann.path_b if path == ann.path_a else ann.path_a
                p = _prefix(idx)
                _insert(idx, [f"{p}# ≡ {other}: {label}\n"])

        elif ann.kind == AnnotationKind.SUPPRESS:
            # Tombstone for now; full block removal is a future feature
            if ann.path is None:
                continue
            idx = _find_line_for_path(lines, ann.path)
            if idx is None:
                continue
            p = _prefix(idx)
            reason = (ann.reason or "").strip()
            _insert(idx, [f"{p}# suppressed: {reason}\n"])

    result: list[str] = []
    for i, line in enumerate(lines):
        if i in insertions:
            result.extend(insertions[i])
        result.append(line)

    return "".join(result)
