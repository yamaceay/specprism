"""
differ.py  -  Produce a unified diff of two serialized IR YAML strings.
"""

from __future__ import annotations

import difflib


def diff_yaml(
    yaml_a: str,
    yaml_b: str,
    label_a: str = "a",
    label_b: str = "b",
    context_lines: int = 3,
) -> str:
    """Return a unified diff string comparing *yaml_a* to *yaml_b*.

    Args:
        yaml_a: Serialized IR YAML for the first spec.
        yaml_b: Serialized IR YAML for the second spec.
        label_a: Header label for the first spec (shown after ``---``).
        label_b: Header label for the second spec (shown after ``+++``).
        context_lines: Number of unchanged context lines around each hunk.

    Returns:
        A unified-diff string, or an empty string if the two YAMLs are identical.
    """
    lines_a = yaml_a.splitlines(keepends=True)
    lines_b = yaml_b.splitlines(keepends=True)

    diff = difflib.unified_diff(
        lines_a,
        lines_b,
        fromfile=label_a,
        tofile=label_b,
        n=context_lines,
    )
    return "".join(diff)
