"""
cli.py  -  specprism command-line interface.

Commands
--------
  parse  <spec>              Normalize one spec to IR YAML
  diff   <spec_a> <spec_b>   Unified diff of two IR YAMLs
  show   <spec> --schema X   Print one resolved schema node

Options
-------
  --output <file>      Write output to file instead of stdout
  --knowhow <file>     Know-how annotation YAML
  --no-endpoints       Skip endpoint nodes (schema-only diff)
  --no-descriptions    Strip descriptions before diff (reduce noise)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
import yaml

from .differ import diff_yaml
from .ir import SpecIR
from .knowhow import KnowhowFile, annotate_yaml
from .resolver import resolve_file
from .serializer import serialize

app = typer.Typer(
    name="specprism",
    help="Normalize OpenAPI specs to a stable IR and diff them.",
    add_completion=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_spec(path: Path) -> dict:
    """Load a JSON or YAML OpenAPI spec file."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def _write_output(text: str, output: Optional[Path]) -> None:
    if output:
        output.write_text(text, encoding="utf-8")
        typer.echo(f"Written to {output}", err=True)
    else:
        sys.stdout.write(text)


def _load_knowhow(knowhow: Optional[Path]) -> Optional[KnowhowFile]:
    if knowhow is None:
        return None
    return KnowhowFile.from_file(str(knowhow))


def _strip_descriptions(ir: SpecIR) -> SpecIR:
    """Return a copy of *ir* with all description fields cleared."""
    data = ir.model_dump()
    _clear_descriptions(data)
    return SpecIR.model_validate(data)


def _clear_descriptions(obj: object) -> None:
    if isinstance(obj, dict):
        obj.pop("description", None)
        for v in obj.values():
            _clear_descriptions(v)
    elif isinstance(obj, list):
        for item in obj:
            _clear_descriptions(item)


def _drop_endpoints(ir: SpecIR) -> SpecIR:
    return ir.model_copy(update={"endpoints": []})


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def parse(
    spec: Path = typer.Argument(..., help="OpenAPI 3.x JSON or YAML file"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file"),
    knowhow: Optional[Path] = typer.Option(None, "--knowhow", help="Know-how YAML"),
    no_endpoints: bool = typer.Option(False, "--no-endpoints", help="Skip endpoints"),
    no_descriptions: bool = typer.Option(
        False, "--no-descriptions", help="Strip descriptions"
    ),
) -> None:
    """Normalize one OpenAPI spec to IR YAML."""
    raw = _load_spec(spec)
    ir = resolve_file(raw)

    if no_endpoints:
        ir = _drop_endpoints(ir)
    if no_descriptions:
        ir = _strip_descriptions(ir)

    yaml_text = serialize(ir)

    kh = _load_knowhow(knowhow)
    if kh:
        yaml_text = annotate_yaml(yaml_text, kh)

    _write_output(yaml_text, output)


@app.command()
def diff(
    spec_a: Path = typer.Argument(..., help="First OpenAPI 3.x JSON or YAML file"),
    spec_b: Path = typer.Argument(..., help="Second OpenAPI 3.x JSON or YAML file"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file"),
    knowhow: Optional[Path] = typer.Option(None, "--knowhow", help="Know-how YAML"),
    no_endpoints: bool = typer.Option(False, "--no-endpoints", help="Skip endpoints"),
    no_descriptions: bool = typer.Option(
        False, "--no-descriptions", help="Strip descriptions"
    ),
) -> None:
    """Produce a unified diff of two OpenAPI specs via their IR."""
    raw_a = _load_spec(spec_a)
    raw_b = _load_spec(spec_b)

    ir_a = resolve_file(raw_a)
    ir_b = resolve_file(raw_b)

    if no_endpoints:
        ir_a = _drop_endpoints(ir_a)
        ir_b = _drop_endpoints(ir_b)
    if no_descriptions:
        ir_a = _strip_descriptions(ir_a)
        ir_b = _strip_descriptions(ir_b)

    yaml_a = serialize(ir_a)
    yaml_b = serialize(ir_b)

    kh = _load_knowhow(knowhow)
    if kh:
        yaml_a = annotate_yaml(yaml_a, kh)
        yaml_b = annotate_yaml(yaml_b, kh)

    label_a = f"{spec_a.stem} ({ir_a.version})"
    label_b = f"{spec_b.stem} ({ir_b.version})"

    result = diff_yaml(yaml_a, yaml_b, label_a=label_a, label_b=label_b)
    if not result:
        typer.echo("Specs are identical after normalization.", err=True)

    _write_output(result, output)


@app.command()
def show(
    spec: Path = typer.Argument(..., help="OpenAPI 3.x JSON or YAML file"),
    schema: str = typer.Option(..., "--schema", help="Schema name to display"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file"),
    no_descriptions: bool = typer.Option(
        False, "--no-descriptions", help="Strip descriptions"
    ),
) -> None:
    """Print one resolved schema node from a spec."""
    raw = _load_spec(spec)
    ir = resolve_file(raw)

    if schema not in ir.schemas:
        typer.echo(f"Schema '{schema}' not found in {spec}.", err=True)
        available = ", ".join(sorted(ir.schemas.keys()))
        typer.echo(f"Available schemas: {available}", err=True)
        raise typer.Exit(1)

    node = ir.schemas[schema]
    if no_descriptions:
        node_data = node.model_dump()
        _clear_descriptions(node_data)
        from .ir import SchemaNode
        node = SchemaNode.model_validate(node_data)

    from .serializer import _schema_to_dict
    import yaml as _yaml

    yaml_text = _yaml.dump(
        _schema_to_dict(node),
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    _write_output(yaml_text, output)
